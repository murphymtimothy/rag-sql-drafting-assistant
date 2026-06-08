import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from assistant.sql_assistant import (
    answer_question,
    log_result,
    _extract_sql,
    _tokenize,
    _dedupe,
    _sparse_search,
    _rrf_fuse,
    _rerank,
)


# --- _extract_sql ---

def test_extract_sql_from_code_fence():
    content = "Here is the query:\n```sql\nSELECT * FROM members\n```\nExplanation follows."
    assert _extract_sql(content) == "SELECT * FROM members"

def test_extract_sql_from_generic_fence():
    content = "```\nSELECT loan_id FROM loans\n```"
    assert _extract_sql(content) == "SELECT loan_id FROM loans"

def test_extract_sql_no_fence_returns_empty():
    content = "I cannot answer this from the provided schema."
    assert _extract_sql(content) == ""


# --- retrieval helpers (hybrid: dense + BM25 sparse + cross-encoder rerank) ---

def test_dedupe_preserves_first_seen_order():
    assert _dedupe(["a.md", "b.md", "a.md", "c.md", "b.md"]) == ["a.md", "b.md", "c.md"]

def test_tokenize_lowercases_and_splits_on_non_word():
    assert _tokenize("Member_ID JOIN  Loans!") == ["member_id", "join", "loans"]

def test_sparse_search_empty_dir_returns_empty(tmp_path):
    # Returns [] whether or not rank_bm25 is installed (no docs to rank).
    assert _sparse_search("anything", k_sparse=5, schema_docs_path=tmp_path) == []

def test_sparse_search_ranks_lexically_relevant_doc_first(tmp_path):
    pytest.importorskip("rank_bm25")
    # Use several docs: BM25 IDF degenerates to 0 on a 2-doc corpus (a term in 1 of 2
    # docs has IDF=log(1)=0), so a realistic multi-doc corpus is needed for the test.
    (tmp_path / "members.md").write_text(
        "members table member_id first_name last_name email mailing address", encoding="utf-8"
    )
    (tmp_path / "loans.md").write_text(
        "loans table loan_id principal balance days_past_due delinquency interest rate", encoding="utf-8"
    )
    (tmp_path / "accounts.md").write_text(
        "accounts table account_id current_balance available_balance status deposit", encoding="utf-8"
    )
    (tmp_path / "cards.md").write_text(
        "card accounts table card_account_id points_balance rewards statement", encoding="utf-8"
    )
    out = _sparse_search("loans past due delinquency principal", k_sparse=5, schema_docs_path=tmp_path)
    assert out, "expected at least one BM25 hit"
    assert out[0]["file"] == "loans.md"

def test_rrf_fuse_ranks_doc_present_in_both_lists_first():
    dense = [{"file": "a.md", "text": "A"}, {"file": "b.md", "text": "B"}]
    sparse = [{"file": "b.md", "text": "B"}, {"file": "c.md", "text": "C"}]
    fused = _rrf_fuse(dense, sparse)
    files = [c["file"] for c in fused]
    assert files[0] == "b.md"  # appears near top of both → highest combined RRF score
    assert set(files) == {"a.md", "b.md", "c.md"}

def test_rerank_falls_back_to_fusion_order_when_model_unavailable(monkeypatch):
    import assistant.sql_assistant as sa

    def _boom():
        raise RuntimeError("reranker not installed")

    monkeypatch.setattr(sa, "_get_reranker", _boom)
    cands = [{"file": f"{i}.md", "text": str(i)} for i in range(8)]
    out = sa._rerank("q", cands, top_k=5)
    assert [c["file"] for c in out] == [f"{i}.md" for i in range(5)]

def test_rerank_orders_by_cross_encoder_scores(monkeypatch):
    import assistant.sql_assistant as sa

    class FakeCrossEncoder:
        def predict(self, pairs):
            # Score == numeric value of the passage text, so higher text ranks first.
            return [float(passage) for _q, passage in pairs]

    monkeypatch.setattr(sa, "_get_reranker", lambda: FakeCrossEncoder())
    cands = [{"file": f"{i}.md", "text": str(i)} for i in range(5)]
    out = sa._rerank("q", cands, top_k=3)
    assert [c["file"] for c in out] == ["4.md", "3.md", "2.md"]


# --- answer_question ---

def _make_mock_openai(embed_vector, completion_text):
    mock = MagicMock()
    embed_resp = MagicMock()
    embed_resp.data = [MagicMock(embedding=embed_vector)]
    mock.embeddings.create.return_value = embed_resp
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=completion_text))]
    mock.chat.completions.create.return_value = completion
    return mock


def _make_mock_chroma(chunks, filenames):
    collection = MagicMock()
    collection.query.return_value = {
        "documents": [chunks],
        "metadatas": [[{"file_name": f} for f in filenames]],
    }
    collection.count.return_value = len(chunks)
    client = MagicMock()
    client.get_collection.return_value = collection
    return client


def test_answer_question_rag_on_returns_citations(tmp_path):
    mock_ollama = _make_mock_openai(
        embed_vector=[0.1] * 768,
        completion_text="```sql\nSELECT m.member_id, l.loan_id FROM members m JOIN loans l ON m.member_id = l.member_id\n```\nJoins members to loans.",
    )
    mock_chroma_client = _make_mock_chroma(
        chunks=["members table content...", "loans table content..."],
        filenames=["members.md", "loans.md"],
    )

    # schema_docs_path=tmp_path (empty) → no BM25 sparse hits; force the reranker to be
    # unavailable so retrieval is deterministic dense-only for this assertion.
    with patch("assistant.sql_assistant.ollama", mock_ollama), \
         patch("assistant.sql_assistant.chromadb.PersistentClient", return_value=mock_chroma_client), \
         patch("assistant.sql_assistant._get_reranker", side_effect=RuntimeError("no reranker")):
        result = answer_question(
            "Show members with their loan IDs",
            rag_enabled=True,
            chroma_path=tmp_path,
            schema_docs_path=tmp_path,
        )

    assert result["rag_enabled"] is True
    assert result["citations"] == ["members.md", "loans.md"]
    assert "members" in result["sql"].lower()
    assert result["chunk_count"] == 2
    assert result["eval_score"] is None


def test_answer_question_rag_off_has_no_citations(tmp_path):
    mock_ollama = _make_mock_openai(
        embed_vector=[0.1] * 768,
        completion_text="```sql\nSELECT * FROM some_table\n```",
    )
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        result = answer_question("Show all members", rag_enabled=False, chroma_path=tmp_path)

    assert result["rag_enabled"] is False
    assert result["citations"] == []
    assert result["chunk_count"] == 0
    assert result["raw_chunks"] == []


def test_answer_question_chroma_missing_raises_on_rag(tmp_path):
    mock_ollama = _make_mock_openai([0.1] * 768, "")
    missing_path = tmp_path / "nonexistent_chroma"

    mock_client = MagicMock()
    mock_client.get_collection.side_effect = Exception("Collection not found")

    with patch("assistant.sql_assistant.ollama", mock_ollama), \
         patch("assistant.sql_assistant.chromadb.PersistentClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="build_index"):
            answer_question(
                "any question",
                rag_enabled=True,
                chroma_path=missing_path,
                schema_docs_path=missing_path,
            )


# --- answer_question validation wiring (§2d: the validate_sql gate) ---

def test_answer_question_flags_hallucinated_column(tmp_path):
    # loan_status_history has no member_id column (it carries loan_id). The validator
    # must catch it, and answer_question must surface the verdict via result["validation"].
    mock_ollama = _make_mock_openai(
        [0.1] * 768,
        "```sql\nSELECT member_id FROM loan_status_history\n```",
    )
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        result = answer_question("q", rag_enabled=False, chroma_path=tmp_path)

    assert result["validation"]["ok"] is False
    assert result["validation"]["errors"], "expected a binding error for the unknown column"


def test_answer_question_validation_passes_for_clean_sql(tmp_path):
    mock_ollama = _make_mock_openai(
        [0.1] * 768,
        "```sql\nSELECT member_id, first_name FROM members\n```",
    )
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        result = answer_question("q", rag_enabled=False, chroma_path=tmp_path)

    assert result["validation"]["ok"] is True
    assert result["validation"]["errors"] == []


def test_answer_question_decline_skips_validation(tmp_path):
    # A correct schema-gap decline produces no SQL, so validation has nothing to flag.
    mock_ollama = _make_mock_openai(
        [0.1] * 768,
        "I cannot answer this from the provided schema — there is no such table.",
    )
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        result = answer_question("q", rag_enabled=False, chroma_path=tmp_path)

    assert result["sql"] == ""
    assert result["validation"] == {"ok": True, "errors": [], "warnings": []}


def test_log_result_appends_jsonl(tmp_path):
    result = {
        "timestamp": "2026-06-07T14:00:00Z",
        "question": "test",
        "rag_enabled": True,
        "sql": "SELECT 1",
        "explanation": "test",
        "citations": ["members.md"],
        "raw_chunks": ["chunk text here"],
        "chunk_count": 1,
        "latency_ms": 100,
        "model": "qwen2.5-coder:14b",
        "eval_score": None,
        "eval_reason": None,
    }
    log_path = tmp_path / "queries.jsonl"
    log_result(result, logs_path=log_path)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["question"] == "test"
    assert "raw_chunks" not in record, "raw_chunks must not be written to the log"

    log_result(result, logs_path=log_path)
    assert len(log_path.read_text(encoding="utf-8").strip().splitlines()) == 2
