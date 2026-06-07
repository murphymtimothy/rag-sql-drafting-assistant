import json
from pathlib import Path
import pytest
from refresh.refresh_scheduler import _hash_docs, _load_state, _save_state, run_refresh_cycle


def test_hash_docs_is_deterministic(minimal_schema_docs):
    h1 = _hash_docs(minimal_schema_docs)
    h2 = _hash_docs(minimal_schema_docs)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_hash_docs_changes_when_file_changes(minimal_schema_docs):
    h_before = _hash_docs(minimal_schema_docs)
    (minimal_schema_docs / "members.md").write_text("changed content", encoding="utf-8")
    h_after = _hash_docs(minimal_schema_docs)
    assert h_before != h_after


def test_hash_docs_changes_when_file_added(minimal_schema_docs):
    h_before = _hash_docs(minimal_schema_docs)
    (minimal_schema_docs / "new_table.md").write_text("# TABLE: new_table\n", encoding="utf-8")
    h_after = _hash_docs(minimal_schema_docs)
    assert h_before != h_after


def test_load_state_returns_empty_string_when_no_file(tmp_path):
    state_file = tmp_path / "refresh_state.json"
    assert _load_state(state_file) == ""


def test_save_and_load_state_roundtrip(tmp_path):
    state_file = tmp_path / "refresh_state.json"
    _save_state(state_file, "abc123")
    assert _load_state(state_file) == "abc123"


def test_run_refresh_cycle_skipped_when_no_change(minimal_schema_docs, tmp_path, mocker):
    chroma_path = tmp_path / "chroma_db"
    state_file = tmp_path / "refresh_state.json"
    refresh_log = tmp_path / "refresh_log.jsonl"

    current_hash = _hash_docs(minimal_schema_docs)
    _save_state(state_file, current_hash)

    mock_build = mocker.patch("refresh.refresh_scheduler.build_index")
    action = run_refresh_cycle(minimal_schema_docs, chroma_path, state_file, refresh_log)

    assert action == "skipped"
    mock_build.assert_not_called()
    log_records = [json.loads(l) for l in refresh_log.read_text().splitlines()]
    assert log_records[0]["action"] == "skipped"


def test_run_refresh_cycle_reindexed_when_changed(minimal_schema_docs, tmp_path, mocker):
    chroma_path = tmp_path / "chroma_db"
    state_file = tmp_path / "refresh_state.json"
    refresh_log = tmp_path / "refresh_log.jsonl"

    mock_build = mocker.patch("refresh.refresh_scheduler.build_index", return_value=10)
    action = run_refresh_cycle(minimal_schema_docs, chroma_path, state_file, refresh_log)

    assert action == "reindexed"
    mock_build.assert_called_once()
    log_records = [json.loads(l) for l in refresh_log.read_text().splitlines()]
    assert log_records[0]["action"] == "reindexed"

    action2 = run_refresh_cycle(minimal_schema_docs, chroma_path, state_file, refresh_log)
    assert action2 == "skipped"
