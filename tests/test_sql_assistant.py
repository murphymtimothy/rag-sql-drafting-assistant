import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from assistant.sql_assistant import answer_question, log_result, _extract_sql


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

    with patch("assistant.sql_assistant.ollama", mock_ollama), \
         patch("assistant.sql_assistant.chromadb.PersistentClient", return_value=mock_chroma_client):
        result = answer_question("Show members with their loan IDs", rag_enabled=True, chroma_path=tmp_path)

    assert result["rag_enabled"] is True
    assert "members.md" in result["citations"]
    assert "loans.md" in result["citations"]
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
            answer_question("any question", rag_enabled=True, chroma_path=missing_path)


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
        "model": "gpt-oss:20b",
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
