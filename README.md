# RAG SQL-Drafting Assistant

A local, fully offline SQL-drafting assistant grounded via RAG over a credit-union data warehouse schema.

---

## Executive brief

**The problem.** Analysts spend more time figuring out *which* warehouse table and column to use — and how tables join — than writing the SQL itself. Public AI chatbots make this worse, not better: they don't know our schema, so they confidently invent table names that don't exist (*hallucination*), and they send data to the cloud — a non-starter for a financial institution.

**What we built.** A SQL-drafting assistant that runs **entirely on a local machine** (no internet, no cloud, no member data) and **grounds every answer in our actual schema documentation** using Retrieval-Augmented Generation (RAG). Before the AI writes any SQL, the system retrieves the relevant table docs and hands them to the model as reference. Every answer ships with **citations** — the exact schema docs it used — so a human can verify the grounding instead of trusting it.

**Does it work?** On a curated test set of 15 representative questions (local model `qwen2.5-coder:7b`, 5-run average), grounding accuracy was:

| | Mean grounding score |
|---|---|
| **RAG enabled** | **0.89** |
| No RAG (baseline) | 0.30 |

Same model, same questions — the only difference is whether it could see our schema. Retrieval is what turns a plausible guess into a usable, schema-correct draft. The hardest cases (cross-subject joins like "members → loans → delinquency status") score a perfect 1.0 with RAG. The local model was chosen via a five-model bake-off — see [`docs/model-selection.md`](docs/model-selection.md).

**Why it's safe.** Both the AI and the embedding model run locally via Ollama — nothing leaves the machine. The POC uses fictional mock data. The path to a real warehouse extracts **schema metadata only** (never row data) over **read-only** access to system catalog views. Every query is logged for audit. Schema knowledge lives in plain files we control, not baked into model weights — so it can be reviewed, corrected, and updated without retraining.

**What it is *not*.** It *drafts* SQL; it does not execute it or replace analyst review. No member-facing decisions, no auto-execution, no fine-tuning. It's a single-analyst proof-of-concept with honest limitations — see the full overview.

📄 **Full detail:** [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — comprehensive plain-English + technical writeup for leadership, analysts, and engineers.

---

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
- Models pulled: `ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text`
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
