# RAG SQL-Drafting Assistant

A local, fully offline SQL-drafting assistant grounded via RAG over a credit-union data warehouse schema.

---

## Executive brief

**The problem.** Analysts spend more time figuring out *which* warehouse table and column to use — and how tables join — than writing the SQL itself. Public AI chatbots make this worse, not better: they don't know our schema, so they confidently invent table names that don't exist (*hallucination*), and they send data to the cloud — a non-starter for a financial institution.

**What we built.** A SQL-drafting assistant that runs **entirely on a local machine** (no internet, no cloud, no member data) and **grounds every answer in our actual schema documentation** using Retrieval-Augmented Generation (RAG). Before the AI writes any SQL, the system retrieves the relevant table docs and hands them to the model as reference. Every answer ships with **citations** — the exact schema docs it used — so a human can verify the grounding instead of trusting it.

**Does it work?** Yes — and we measure it. The eval harness runs every curated question twice (RAG on vs. RAG off) and scores whether the drafted SQL references only real tables/columns and includes the expected ones. In the five-model bake-off that selected the local model, RAG roughly **tripled** grounding accuracy versus the no-RAG baseline — e.g. `qwen2.5-coder:7b` scored **0.89** with RAG vs **0.30** without (5-run average) on a curated 15-question set:

| | Mean grounding score (qwen2.5-coder:7b) |
|---|---|
| **RAG enabled** | **0.89** |
| No RAG (baseline) | 0.30 |

Same questions, same model — the only difference is whether it could see our schema. The default model is now **`qwen2.5-coder:14b`** for extra headroom on Redwood's harder table/column disambiguation; run `python eval/run_eval.py` to regenerate `logs/eval_report.md` for the current stack. The hardest cases (cross-subject joins like "members → loans → delinquency status") score a perfect 1.0 with RAG. The local model was chosen via the bake-off — see [`docs/model-selection.md`](docs/model-selection.md).

**Why it's safe.** Both the AI and the embedding model run locally via Ollama — nothing leaves the machine. The POC uses fictional mock data. The path to a real warehouse extracts **schema metadata only** (never row data) over **read-only** access to system catalog views. Every query is logged for audit. Schema knowledge lives in plain files we control, not baked into model weights — so it can be reviewed, corrected, and updated without retraining.

**What it is *not*.** It *drafts* SQL; it does not execute it or replace analyst review. No member-facing decisions, no auto-execution, no fine-tuning. It's a single-analyst proof-of-concept with honest limitations — see the full overview.

📄 **Full detail:** [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — comprehensive plain-English + technical writeup for leadership, analysts, and engineers.

---

## What this is

A personal proof-of-concept demonstrating that a local LLM (no cloud API, no member data) can draft accurate, schema-grounded SQL by retrieving relevant table/column documentation at query time. Built as a learning artifact and internal proposal evidence base.

**Stack:** Ollama (inference) · **Open WebUI** (off-the-shelf team GUI) · LlamaIndex (ingestion) · ChromaDB (vector store) · `bge-m3` embedder · `bge-reranker-v2-m3` reranker · OpenAI Python SDK (pointed at Ollama) · Python 3.11+

**Two ways to use it:**
- **Open WebUI** — the team-facing GUI. Off-the-shelf, multi-user, self-hostable on-prem. Setup is fully documented and reproducible in [`docs/OPEN_WEBUI_SETUP.md`](docs/OPEN_WEBUI_SETUP.md).
- **Scripted pipeline + CLI** — the validated ground-truth core that the eval proves correct and that mirrors the GUI's retrieval. This is *not* the user-facing app; it is the reference implementation and evidence base.

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
- Models pulled: `ollama pull qwen2.5-coder:14b && ollama pull bge-m3`
  - `nomic-embed-text` is an acceptable embedder fallback (`set RAG_EMBED_MODEL=nomic-embed-text`).
  - The reranker `bge-reranker-v2-m3` is downloaded automatically by `sentence-transformers` on first use (Python path) and by Open WebUI on first use (GUI) — it is not an Ollama model.
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

## Retrieval config & parity with Open WebUI

The scripted pipeline and Open WebUI are **two retrieval implementations of the same config**, so the eval is a faithful proxy for what the GUI does. Both are aligned to:

- **One chunk per table doc** — `ingest/build_index.py` loads each `.md` as a single flat document (`CHUNK_SIZE=8192`, overlap 0, **no** markdown-header splitting), so a table's documentation is never split across chunks.
- **Top-K = 5** (`DEFAULT_K`).
- **Hybrid retrieval** — dense vectors (Chroma + `bge-m3`) fused with **BM25** sparse retrieval over `schema_docs/` via Reciprocal Rank Fusion.
- **Reranking** — the fused candidates are reranked by the `bge-reranker-v2-m3` cross-encoder down to the final Top-5.
- **Verbatim T-SQL system prompt** — `SYSTEM_PROMPT` in `assistant/sql_assistant.py` is identical to the prompt pasted into the Open WebUI model.

If `rank-bm25` / `sentence-transformers` aren't installed, the Python path **degrades gracefully to dense-only** retrieval (the eval report header records which mode actually ran). The Open WebUI side of this config lives in [`docs/OPEN_WEBUI_SETUP.md`](docs/OPEN_WEBUI_SETUP.md).

## Eval report

`python eval/run_eval.py` produces `logs/eval_report.md` — a side-by-side RAG-on/off comparison with automated grounding scores across 15 curated questions. The report header records the exact retrieval config (embedder, Top-K, reranker, mode) used for that run. This on-demand harness is the **evidence layer**: no service, no UI, just `python eval/run_eval.py`.

## Real warehouse

To point at a real MS SQL Server warehouse instead of mock docs:

```powershell
$env:SQL_SERVER_DSN = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=...;DATABASE=...;UID=...;PWD=..."
python extraction/extract_schema_from_sqlserver.py
python ingest/build_index.py
```

The extraction script requires read-only SELECT on system catalog views only — no write access, no access to table data. The full home → on-prem porting plan (why row count is irrelevant, where disambiguation gets hard, and which scaling paths to keep open) is in [`docs/PORTING_TO_ONPREM.md`](docs/PORTING_TO_ONPREM.md).
