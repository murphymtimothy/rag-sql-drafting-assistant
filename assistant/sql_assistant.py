import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from openai import OpenAI

CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
LOGS_PATH = Path(__file__).parent.parent / "logs" / "queries.jsonl"
COLLECTION = "schema_docs"
DEFAULT_MODEL = "gpt-oss:20b"
DEFAULT_K = 5

SYSTEM_PROMPT = (
    "You are a SQL-drafting assistant for a credit union's internal data warehouse.\n"
    "When schema context is provided, you MUST only reference tables and columns that "
    "appear in that context — never invent table or column names.\n"
    "If the schema context does not contain what is needed to answer the question, "
    "say so explicitly rather than guessing.\n"
    "Always provide:\n"
    "1. The SQL query in a ```sql code block\n"
    "2. A brief explanation of the join logic and any assumptions you made."
)

ollama = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def _embed(text: str) -> list[float]:
    resp = ollama.embeddings.create(model="nomic-embed-text", input=text)
    return resp.data[0].embedding


def _retrieve(
    question: str, k: int, chroma_path: Path
) -> tuple[list[str], list[str], list[str]]:
    """Return (chunk_texts, per_chunk_filenames, deduplicated_citation_filenames).

    per_chunk_filenames stays index-aligned with chunk_texts so each chunk can be
    labelled with its own source; citations is the de-duplicated list for display.
    """
    try:
        client = chromadb.PersistentClient(path=str(chroma_path))
        collection = client.get_collection(COLLECTION)
    except Exception as exc:
        raise RuntimeError(
            f"Chroma collection '{COLLECTION}' not found at {chroma_path}. "
            "Run `python ingest/build_index.py` first."
        ) from exc

    actual_k = min(k, collection.count())
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
    chunks: list[str] = results["documents"][0]
    filenames: list[str] = [
        meta.get("file_name", "unknown") for meta in results["metadatas"][0]
    ]
    seen: set[str] = set()
    citations: list[str] = []
    for f in filenames:
        if f not in seen:
            seen.add(f)
            citations.append(f)
    return chunks, filenames, citations


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
        chunks, chunk_files, citations = _retrieve(question, k, chroma_path)

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

    resp = ollama.chat.completions.create(model=model, messages=messages)
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


def _cli_loop(chroma_path: Path = CHROMA_PATH, model: str = DEFAULT_MODEL) -> None:
    print(f"SQL Assistant (model={model}, RAG={'on' if chroma_path.exists() else 'OFF — run build_index.py'})")
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
