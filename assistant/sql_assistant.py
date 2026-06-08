import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from openai import OpenAI

ROOT = Path(__file__).parent.parent
CHROMA_PATH = ROOT / "chroma_db"
SCHEMA_DOCS = ROOT / "schema_docs"
LOGS_PATH = ROOT / "logs" / "queries.jsonl"
COLLECTION = "schema_docs"

DEFAULT_MODEL = "qwen2.5-coder:14b"  # non-thinking coder; see docs/model-selection.md
# Embedding model. bge-m3 is the default (sparse+dense, pairs with hybrid search at
# scale). nomic-embed-text is an acceptable fallback — override with RAG_EMBED_MODEL.
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "bge-m3")
# Cross-encoder reranker applied to fused candidates (see _retrieve). Same model the
# Open WebUI front end uses, so the scripted pipeline and the GUI rank identically.
RERANKER_MODEL = os.environ.get("RAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

DEFAULT_K = 5  # final retrieved chunks handed to the model (Top-K)
# Candidate-pool sizes for each retriever before fusion + rerank. At ~20 docs these
# effectively grab everything; at Redwood scale (thousands of chunks) they are the
# recall knob — widen them and let the reranker do the precision work.
K_DENSE = int(os.environ.get("RAG_K_DENSE", "20"))
K_SPARSE = int(os.environ.get("RAG_K_SPARSE", "20"))

# REASONING_EFFORT is applied only when a gpt-oss reasoning model is selected (see the
# guard in answer_question). gpt-oss spends its hidden reasoning channel before the final
# answer; at default effort that overflows Ollama's 4096-token context window and
# `content` comes back empty (finish_reason=length). The default qwen2.5-coder model is
# NOT a reasoning model and is unaffected by this setting — it is the reason the
# "no output" bug does not occur with the default stack.
REASONING_EFFORT = "low"

# Section 5.1 T-SQL grounding system prompt — used VERBATIM here and in the Open WebUI
# model config (docs/OPEN_WEBUI_SETUP.md step 3) so both retrieval paths prompt
# identically. The Open WebUI RAG template (docs/OPEN_WEBUI_SETUP.md §1) is kept neutral
# so it reinforces — never contradicts — these rules; this prompt is the single source of
# behavioral truth across both paths.
SYSTEM_PROMPT = (
    "You are a SQL-drafting assistant for analysts at a credit union. You draft "
    "Microsoft SQL Server (T-SQL) SELECT queries for a human analyst to review and "
    "run. You never execute SQL and you never modify data.\n"
    "\n"
    "# Grounding — your most important rule\n"
    "- The Schema Context provided with each question is the complete and "
    "authoritative schema. Use ONLY tables and columns that appear there.\n"
    "- Never invent, assume, or recall a table or column name from memory — not even "
    "names that are \"standard\" for banking or credit-union data. If you are about to "
    "write a name that does not appear in the Schema Context, stop: that is a "
    "hallucination, not an answer.\n"
    "- If the Schema Context lacks a table or column needed to answer, do not write "
    "SQL that uses it. Instead say plainly what is missing and name the specific table "
    "doc(s) you would need. A correct \"I can't answer that from the provided schema\" "
    "is a success, not a failure.\n"
    "- Before you finalize, re-read your query and confirm that every table, every "
    "column, and every alias you reference is defined — columns in the Schema Context, "
    "aliases in your own query.\n"
    "\n"
    "# Dialect — Microsoft SQL Server (T-SQL) only\n"
    "- Use: TOP (not LIMIT); GETDATE() / SYSDATETIME() (not NOW()); EOMONTH(), "
    "DATEADD(), DATEDIFF(); ISNULL() / COALESCE(); OFFSET ... FETCH for paging; "
    "[bracket] quoting; window functions (ROW_NUMBER, LAG, LEAD, SUM() OVER ()).\n"
    "- Never use MySQL- or Postgres-only syntax: no LIMIT, no backticks, no NOW(), no "
    "ILIKE, no :: casts.\n"
    "- Draft read-only SELECT queries unless explicitly asked otherwise. Never emit "
    "INSERT / UPDATE / DELETE / DDL by default.\n"
    "\n"
    "# Correctness patterns — apply when the question calls for them\n"
    "These analytic shapes are easy to get subtly wrong. When relevant, follow them; "
    "do not force them onto simple queries.\n"
    "- Most-recent / current value per entity: select the latest row with "
    "ROW_NUMBER() OVER (PARTITION BY <entity_key> ORDER BY <date> DESC, <pk> DESC) and "
    "keep where it equals 1. Always include the primary key as a tiebreaker so "
    "same-date ties don't return duplicates.\n"
    "- Running-balance / ledger columns (a column that already carries a cumulative "
    "total on each row, e.g. a points or account balance): read it from the latest "
    "qualifying row using the pattern above. Never aggregate it with MAX(), SUM(), or "
    "AVG() — the running total already includes prior rows, so SUM multiplies it and "
    "MAX returns the high-water mark, not the closing balance.\n"
    "- Period-over-period change (month-over-month, etc.): (1) reduce to one value per "
    "entity per period first — typically the period's closing value via the latest-row "
    "pattern within each period; (2) then apply LAG(value) OVER (PARTITION BY <entity> "
    "ORDER BY <period>) to fetch the prior period; (3) subtract current - prior. Do "
    "not collapse to a single latest row before the LAG, or there is no prior period "
    "left to compare against. Skeleton (substitute real names from the Schema "
    "Context):\n"
    "    WITH per_period AS (\n"
    "        SELECT <entity>, EOMONTH(<date>) AS period_end, <value>,\n"
    "               ROW_NUMBER() OVER (PARTITION BY <entity>, EOMONTH(<date>)\n"
    "                                  ORDER BY <date> DESC, <pk> DESC) AS rn\n"
    "        FROM <ledger_table>\n"
    "    )\n"
    "    SELECT <entity>, period_end, <value>,\n"
    "           <value> - LAG(<value>) OVER (PARTITION BY <entity> ORDER BY "
    "period_end) AS mom_change\n"
    "    FROM per_period\n"
    "    WHERE rn = 1;\n"
    "- One-to-many joins: when a join fans out (one parent -> many children), "
    "aggregate or filter the child side to the intended grain before joining so rows "
    "aren't double-counted.\n"
    "\n"
    "# Output\n"
    "- Give the T-SQL in a single ```sql code block, then 2-3 sentences explaining the "
    "join path and any assumptions.\n"
    "- If you declined because of a schema gap, give no SQL — just the explanation of "
    "what's missing.\n"
    "- End by naming the schema doc(s) you used as citations."
)

ollama = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def _embed(text: str, model: str = EMBED_MODEL) -> list[float]:
    resp = ollama.embeddings.create(model=model, input=text)
    return resp.data[0].embedding


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _dedupe(filenames: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for f in filenames:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _dense_search(question: str, k_dense: int, chroma_path: Path) -> list[dict]:
    """Dense (vector) retrieval over the persisted Chroma collection.

    Returns a rank-ordered list of {"file": filename, "text": chunk_text}. Raises
    RuntimeError with a build_index hint if the collection is missing or empty.
    """
    try:
        client = chromadb.PersistentClient(path=str(chroma_path))
        collection = client.get_collection(COLLECTION)
    except Exception as exc:
        raise RuntimeError(
            f"Chroma collection '{COLLECTION}' not found at {chroma_path}. "
            "Run `python ingest/build_index.py` first."
        ) from exc

    actual_k = min(k_dense, collection.count())
    if actual_k == 0:
        raise RuntimeError(
            f"Chroma index at {chroma_path} is empty. "
            "Run `python ingest/build_index.py` first."
        )

    embedding = _embed(question)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=actual_k,
        include=["documents", "metadatas"],
    )
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    return [
        {"file": metas[i].get("file_name", "unknown"), "text": docs[i]}
        for i in range(len(docs))
    ]


def _sparse_search(question: str, k_sparse: int, schema_docs_path: Path) -> list[dict]:
    """BM25 (lexical/sparse) retrieval over schema_docs/*.md.

    This is the sparse half of hybrid retrieval. Returns rank-ordered
    {"file": filename, "text": doc_text}. Returns [] when rank_bm25 is not installed
    (the pipeline then degrades to dense-only) or no docs are present, so the scripted
    path still runs without the optional dependency.
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return []

    files = sorted(schema_docs_path.glob("*.md")) if schema_docs_path.exists() else []
    if not files:
        return []

    texts = [f.read_text(encoding="utf-8") for f in files]
    corpus = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(question))

    order = sorted(range(len(files)), key=lambda i: scores[i], reverse=True)
    ranked = [
        {"file": files[i].name, "text": texts[i]}
        for i in order
        if scores[i] > 0
    ]
    return ranked[:k_sparse]


def _rrf_fuse(dense: list[dict], sparse: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion of two rank-ordered candidate lists, keyed by filename.

    One-chunk-per-table-doc makes the filename a stable join key across both retrievers.
    RRF is order-only (no score normalization needed) and is the standard hybrid-merge.
    """
    fused: dict[str, float] = {}
    text_by_file: dict[str, str] = {}
    for ranked_list in (dense, sparse):
        for rank, cand in enumerate(ranked_list):
            f = cand["file"]
            fused[f] = fused.get(f, 0.0) + 1.0 / (k + rank + 1)
            text_by_file.setdefault(f, cand["text"])
    order = sorted(fused, key=lambda f: fused[f], reverse=True)
    return [{"file": f, "text": text_by_file[f]} for f in order]


_reranker = None  # lazily-loaded cross-encoder; cached across calls


def _get_reranker():
    """Load and cache the bge-reranker-v2-m3 cross-encoder. Raises if unavailable."""
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANKER_MODEL)
    return _reranker


def reranker_available() -> bool:
    try:
        _get_reranker()
        return True
    except Exception:
        return False


def _rerank(question: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Cross-encoder rerank of fused candidates down to top_k.

    Falls back to the fusion order (candidates[:top_k]) if the reranker cannot be
    loaded, so the pipeline still works without sentence-transformers installed.
    """
    if not candidates:
        return []
    try:
        ce = _get_reranker()
    except Exception:
        return candidates[:top_k]
    scores = ce.predict([[question, c["text"]] for c in candidates])
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    return [candidates[i] for i in order[:top_k]]


def _retrieve(
    question: str,
    k: int = DEFAULT_K,
    chroma_path: Path = CHROMA_PATH,
    schema_docs_path: Path = SCHEMA_DOCS,
    k_dense: int = K_DENSE,
    k_sparse: int = K_SPARSE,
) -> tuple[list[str], list[str], list[str]]:
    """Hybrid retrieval: dense + sparse (BM25), fused via RRF, reranked to Top-K.

    Returns (chunk_texts, per_chunk_filenames, deduped_citation_filenames). The
    per_chunk_filenames stay index-aligned with chunk_texts; citations is the
    de-duplicated display list. When BM25/reranker deps are absent this degrades to
    pure dense retrieval (see _sparse_search / _rerank), which is exactly the behavior
    the unit tests exercise.
    """
    dense = _dense_search(question, k_dense, chroma_path)
    sparse = _sparse_search(question, k_sparse, schema_docs_path)
    fused = _rrf_fuse(dense, sparse) if sparse else dense
    top = _rerank(question, fused, k)

    chunks = [c["text"] for c in top]
    filenames = [c["file"] for c in top]
    return chunks, filenames, _dedupe(filenames)


def _extract_sql(content: str) -> str:
    """Extract the first SQL block from the model response."""
    match = re.search(r"```(?:sql)?\s*\n?(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def answer_question(
    question: str,
    rag_enabled: bool = True,
    model: str = DEFAULT_MODEL,
    k: int = DEFAULT_K,
    chroma_path: Path = CHROMA_PATH,
    schema_docs_path: Path = SCHEMA_DOCS,
) -> dict:
    """
    Core assistant function. Returns a result dict with sql, explanation,
    citations, and metadata. Caller is responsible for logging via log_result().
    """
    start = time.monotonic()
    chunks: list[str] = []
    chunk_files: list[str] = []
    citations: list[str] = []

    if rag_enabled:
        chunks, chunk_files, citations = _retrieve(
            question, k, chroma_path, schema_docs_path
        )

    context_block = ""
    if chunks:
        parts = []
        for i, chunk in enumerate(chunks):
            label = chunk_files[i] if i < len(chunk_files) else "unknown"
            parts.append(f"[Source: {label}]\n{chunk}")
        context_block = "\n\n## Schema Context\n\n" + "\n\n---\n\n".join(parts)

    user_content = f"{context_block}\n\n## Question\n{question}".strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # reasoning_effort applies only to reasoning models (e.g. gpt-oss). Sending it to
    # non-reasoning models such as the Qwen coders is meaningless, so omit it for them.
    create_kwargs: dict = {"model": model, "messages": messages}
    if "gpt-oss" in model:
        create_kwargs["reasoning_effort"] = REASONING_EFFORT
    resp = ollama.chat.completions.create(**create_kwargs)
    content = resp.choices[0].message.content

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "rag_enabled": rag_enabled,
        "sql": _extract_sql(content),
        "explanation": content,
        "citations": citations,
        "raw_chunks": chunks,
        "chunk_count": len(chunks),
        "latency_ms": int((time.monotonic() - start) * 1000),
        "model": model,
        "eval_score": None,
        "eval_reason": None,
    }


def log_result(result: dict, logs_path: Path = LOGS_PATH) -> None:
    """Append one JSON record to the query log. raw_chunks omitted to keep log compact."""
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    record = {k: v for k, v in result.items() if k != "raw_chunks"}
    with logs_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _retrieval_mode() -> str:
    """Human-readable description of which retrievers are active, for CLI/eval banners."""
    bm25 = False
    try:
        import rank_bm25  # noqa: F401

        bm25 = True
    except ImportError:
        pass
    rerank = reranker_available()
    if bm25 and rerank:
        return "hybrid (dense+BM25) + bge-reranker-v2-m3"
    if bm25:
        return "hybrid (dense+BM25), reranker unavailable — fusion order"
    return "dense-only (install rank-bm25 + sentence-transformers for hybrid+rerank)"


def _cli_loop(chroma_path: Path = CHROMA_PATH, model: str = DEFAULT_MODEL) -> None:
    print(f"SQL Assistant (model={model}, RAG={'on' if chroma_path.exists() else 'OFF — run build_index.py'})")
    print(f"Retrieval: {_retrieval_mode()}")
    print("Type your question. Enter blank line to quit.\n")
    while True:
        try:
            question = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not question:
            break
        result = answer_question(question, rag_enabled=True, model=model, chroma_path=chroma_path)
        log_result(result)
        print(f"\n{result['explanation']}")
        if result["citations"]:
            print(f"\nSources: {', '.join(result['citations'])}")
        print(f"({result['latency_ms']}ms)\n")


if __name__ == "__main__":
    _cli_loop()
# end of module
