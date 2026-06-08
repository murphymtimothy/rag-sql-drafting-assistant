import os
import shutil
from pathlib import Path

import chromadb
from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"
CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
COLLECTION = "schema_docs"

# Embedding model — bge-m3 by default (matches Open WebUI). nomic-embed-text is an
# acceptable fallback: set RAG_EMBED_MODEL=nomic-embed-text.
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "bge-m3")

# One chunk per table doc. The window is large enough that a whole table doc — even one
# with many columns — stays a single node; overlap is 0 and there is NO markdown-header
# splitting (we read each file flat, below). bge-m3 accepts up to 8192 tokens.
CHUNK_SIZE = 8192
CHUNK_OVERLAP = 0


def _load_docs(schema_docs_path: Path) -> list[Document]:
    """One Document per .md file, read flat.

    Building Document objects directly (instead of SimpleDirectoryReader's markdown
    reader) guarantees a table's documentation is never split across multiple
    documents on its headers — the retrieval parity requirement in Section 4.4.
    """
    docs: list[Document] = []
    for p in sorted(schema_docs_path.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        if text.strip():
            docs.append(Document(text=text, metadata={"file_name": p.name}))
    return docs


def build_index(
    schema_docs_path: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
) -> int:
    """Wipe and rebuild the Chroma index from schema_docs_path. Returns chunk count."""
    if chroma_path.exists():
        shutil.rmtree(chroma_path)

    Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL)
    # Flat one-chunk-per-doc node parser: large window, no overlap, no header splitting.
    Settings.node_parser = SentenceSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    docs = _load_docs(schema_docs_path)
    if not docs:
        raise RuntimeError(
            f"No .md files found in {schema_docs_path}. "
            "Add schema docs (or run extraction/extract_schema_from_sqlserver.py)."
        )

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(COLLECTION)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    VectorStoreIndex.from_documents(docs, storage_context=storage_context)

    chunk_count = collection.count()
    if chunk_count == 0:
        raise RuntimeError(
            f"Index built but contains 0 chunks. Check that {schema_docs_path} contains "
            f".md files and that Ollama is running with {EMBED_MODEL} pulled."
        )
    return chunk_count


if __name__ == "__main__":
    count = build_index()
    print(f"Index built: {count} chunks from {SCHEMA_DOCS} (embed={EMBED_MODEL})")
    print("Expected: one chunk per table doc. If chunk count > number of .md files, "
          "a doc exceeded the chunk window and was split — raise CHUNK_SIZE.")
