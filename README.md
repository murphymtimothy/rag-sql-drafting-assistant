# RAG SQL-Drafting Assistant

A local, fully offline SQL-drafting assistant grounded via RAG over a credit-union data warehouse schema.

## What this is

A personal proof-of-concept demonstrating that a local LLM (no cloud API, no member data) can draft accurate, schema-grounded SQL by retrieving relevant table/column documentation at query time. Built as a learning artifact and internal proposal evidence base.

**Stack:** Ollama · LlamaIndex · ChromaDB · OpenAI Python SDK (pointed at Ollama) · Python 3.11+

## Project layout

```
schema_docs/        Mock warehouse schema docs (20 tables, 5 subject areas)
ingest/             build_index.py — chunk → embed → persist to Chroma
assistant/          sql_assistant.py — retrieval + prompting + citations + CLI
eval/               checker.py, test_questions.yaml, run_eval.py — grounding eval harness
refresh/            refresh_scheduler.py — hash-detect + reindex on a configurable interval
extraction/         extract_schema_from_sqlserver.py — real MS SQL Server → schema docs
logs/               queries.jsonl, refresh_log.jsonl (gitignored)
tests/              Unit + integration tests (pytest)
```

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) running locally
- Models pulled: `ollama pull gpt-oss:20b && ollama pull nomic-embed-text`
- (Optional) ODBC Driver 17 for SQL Server — only needed for the real-DB extraction script

## Quick start

```powershell
pip install -r requirements.txt

# Build the index from mock schema docs
python ingest/build_index.py

# Chat with the assistant
python assistant/sql_assistant.py

# Run the full RAG-on vs. no-RAG eval
python eval/run_eval.py

# Start the schema-refresh scheduler (demo mode, 2-minute interval)
python refresh/refresh_scheduler.py --interval 120
```

## Eval report

`python eval/run_eval.py` produces `logs/eval_report.md` — a side-by-side RAG-on/off comparison with automated grounding scores across 15 curated questions.

## Real warehouse

To point at a real MS SQL Server warehouse instead of mock docs:

```powershell
$env:SQL_SERVER_DSN = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=...;DATABASE=...;UID=...;PWD=..."
python extraction/extract_schema_from_sqlserver.py
python ingest/build_index.py
```

The extraction script requires read-only SELECT on system catalog views only — no write access, no access to table data.
