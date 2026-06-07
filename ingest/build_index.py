import shutil
from pathlib import Path

import chromadb
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

SCHEMA_DOCS = Path(__file__).parent.parent / "schema_docs"
CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
COLLECTION = "schema_docs"
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128


def build_index(
    schema_docs_path: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
) -> int:
    """Wipe and rebuild the Chroma index from schema_docs_path. Returns chunk count."""
    if chroma_path.exists():
        shutil.rmtree(chroma_path)

    Settings.embed_model = OllamaEmbedding(model_name="nomic-embed-text")
    Settings.chunk_size = CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP

    docs = SimpleDirectoryReader(
        str(schema_docs_path),
        recursive=False,
        required_exts=[".md"],
    ).load_data()

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(COLLECTION)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    VectorStoreIndex.from_documents(docs, storage_context=storage_context)

    chunk_count = collection.count()
    if chunk_count == 0:
        raise RuntimeError(
            f"Index built but contains 0 chunks. Check that {schema_docs_path} contains .md files "
            "and that Ollama is running with nomic-embed-text pulled."
        )
    return chunk_count


if __name__ == "__main__":
    count = build_index()
    print(f"Index built: {count} chunks from {SCHEMA_DOCS}")
