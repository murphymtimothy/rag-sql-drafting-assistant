import os
import pytest
from pathlib import Path
from ingest.build_index import build_index

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("OLLAMA_RUNNING") != "1",
    reason="Requires Ollama running. Set OLLAMA_RUNNING=1 to enable.",
)
def test_build_index_returns_positive_chunk_count(tmp_path):
    chroma_path = tmp_path / "chroma_db"
    count = build_index(schema_docs_path=SCHEMA_DOCS, chroma_path=chroma_path)
    assert count > 0, "Expected at least one chunk to be indexed"
    assert chroma_path.exists(), "Chroma DB directory should be created"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("OLLAMA_RUNNING") != "1",
    reason="Requires Ollama running. Set OLLAMA_RUNNING=1 to enable.",
)
def test_build_index_wipes_and_rebuilds(tmp_path):
    chroma_path = tmp_path / "chroma_db"
    count_first = build_index(schema_docs_path=SCHEMA_DOCS, chroma_path=chroma_path)
    count_second = build_index(schema_docs_path=SCHEMA_DOCS, chroma_path=chroma_path)
    assert count_first == count_second, "Rebuilding should produce the same chunk count"
