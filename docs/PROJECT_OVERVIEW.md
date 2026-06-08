# RAG SQL-Drafting Assistant — Project Overview

**A plain-English (but technically complete) guide to what we built, why we built it, and what it proves.**

| | |
|---|---|
| **Audience** | Leadership (technical and non-technical), data analysts, engineers |
| **Status** | Working proof-of-concept (POC) — runs end-to-end on a single workstation |
| **Date** | 2026-06-08 |
| **One-line summary** | A private, offline assistant that drafts accurate SQL for our data warehouse by *looking up* the real schema before it answers — and citing exactly which tables it used. |

---

## 1. Executive summary (read this first)

Analysts at the credit union spend a meaningful slice of their time writing SQL against a large, sprawling data warehouse. The hard part usually isn't the SQL syntax — it's **knowing the schema**: which of the hundreds of tables holds the data you need, what the columns are actually called, and how the tables join together. That knowledge lives in a handful of people's heads and in scattered documentation.

General-purpose AI chatbots are tempting for this, but they have two disqualifying problems for our use case:

1. **They don't know our schema.** Ask a public chatbot to "write a query for delinquent loans" and it will confidently invent table and column names that don't exist in our warehouse. This is called *hallucination*, and it produces SQL that looks right and runs nowhere.
2. **They send data to the cloud.** Pasting schema details — or worse, member data — into an external service is a non-starter for a financial institution.

This project demonstrates a solution that fixes both problems at once. We built a **SQL-drafting assistant that runs entirely on a local machine** (no internet, no cloud, no member data leaves the building) and that **grounds every answer in our actual schema documentation** using a technique called **Retrieval-Augmented Generation (RAG)**. Before the AI writes a single line of SQL, the system retrieves the relevant table documentation and hands it to the model as reference material. Every answer comes with **citations** — the exact schema documents it drew from — so a human can verify the grounding instead of trusting it.

**The headline result:** on a curated test set of 15 representative questions (local model `qwen2.5-coder:7b`, averaged over 5 runs), the assistant scored **0.89 out of 1.0** for grounding accuracy *with* retrieval turned on, versus **0.30** with retrieval turned off. That gap is the entire point: the same model, same questions, the only difference being whether it could see our schema. Retrieval is what turns a plausible-sounding guess into a usable, schema-correct draft. (These numbers are from the `qwen2.5-coder:7b` bake-off winner; the shipped default is `qwen2.5-coder:14b`, statistically tied in that bake-off and adopted for on-prem headroom — a full re-run on the 14b is pending. The local model was selected via a five-model evaluation — see §6 and [`docs/EVAL_RESULTS.md`](EVAL_RESULTS.md).)

This is a POC and a learning artifact, not a production system. It is deliberately narrow so it could be evaluated quickly and defended honestly. The rest of this document explains how it works, what we proved, what we deliberately left out, and what a production version would require.

---

## 2. The problem, in detail

### 2.1 Why writing warehouse SQL is hard

A credit union data warehouse is a large collection of related tables spanning members, deposit accounts, loans, credit cards, branches, and reference/lookup data. Writing a correct query requires answering questions like:

- *Which* table holds the fact I want? (Is delinquency on the `loans` table, or somewhere else?)
- What are the columns *actually* named? (`status_cd`? `loan_status`? `delinquency_status`?)
- How do I join across subject areas? (How do I connect a member's contact info to their active loans?)
- What conventions apply? (How do I get the *current* address when the table keeps historical rows?)

An analyst who doesn't already carry this map in their head has to go spelunking through documentation, ask a colleague, or trial-and-error against the database. That's slow, and it concentrates knowledge in too few people.

### 2.2 Why a naïve AI chatbot makes it worse, not better

Large language models (LLMs) are extremely good at producing fluent, confident SQL. That's exactly the danger. Without knowledge of our specific schema, an LLM will **hallucinate** — it fills the gaps with names that are statistically plausible but factually wrong. For example, asked about delinquency it might write `SELECT * FROM member_delinquency_summary`, a table that does not exist. The output looks authoritative, wastes the analyst's time, and erodes trust in the tool.

Our own measurements bear this out. With no schema context, grounding drops sharply — to **0.30** across 15 questions, and much of even that comes from the model correctly *declining* the impossible "trick" questions rather than from writing correct SQL. When it did write SQL without the schema, it wasn't producing *bad SQL* in the sense of broken syntax — it was producing *confident SQL about the wrong tables*.

### 2.3 The constraints that rule out the easy options

- **Privacy / regulatory:** member data and even schema details should not be sent to third-party cloud APIs.
- **No fine-tuning on sensitive data:** baking warehouse details into model weights is brittle (it goes stale the moment the schema changes) and risky (sensitive information becomes part of the model).
- **Single-analyst scale for now:** this is a desk tool, not a service to stand up for thousands of concurrent users.

These constraints point directly at the architecture we chose.

---

## 3. What we built (the solution at a glance)

A small, self-contained system with six parts that work together:

```
   ┌─────────────────────┐
   │  Schema docs (×20)   │   Plain-markdown documentation, one file per table,
   │  schema_docs/        │   organized into 5 subject areas. The "knowledge base."
   └──────────┬──────────┘
              │ (1) ingest: chunk → embed → store
              ▼
   ┌─────────────────────┐
   │   Vector index       │   ChromaDB — a searchable store of the schema docs,
   │   (ChromaDB)         │   indexed by *meaning*, not just keywords.
   └──────────┬──────────┘
              │ (2) at query time: find the most relevant docs
              ▼
   ┌─────────────────────┐      ┌──────────────────────┐
   │   The assistant      │◀────▶│  Local LLM (Ollama)  │   Runs on the workstation.
   │  answer_question()   │      │  qwen2.5-coder:14b   │   Nothing leaves the machine.
   └──────────┬──────────┘      └──────────────────────┘
              │ returns SQL + explanation + CITATIONS
              ▼
   ┌─────────────────────┐
   │  Analyst / CLI / GUI │
   └─────────────────────┘

   Supporting machinery:
   • Eval harness  — proves RAG-on beats RAG-off, with automated scores
   • Refresh job   — keeps the index current as the schema changes
   • Extraction    — generates schema docs from a real SQL Server warehouse
   • Logging       — every query recorded for audit and analysis
```

**The technology stack**, in one line: **Ollama** (runs the AI models locally) · **Open WebUI** (the off-the-shelf team GUI — see [`docs/OPEN_WEBUI_SETUP.md`](OPEN_WEBUI_SETUP.md)) · **LlamaIndex** (handles document ingestion) · **ChromaDB** (the searchable vector store) · **`bge-m3`** embedder + **`bge-reranker-v2-m3`** reranker · the **OpenAI Python SDK pointed at Ollama** (so we talk to the local model with a standard, well-understood interface) · **Python 3.11+**.

Crucially, **all compute stays on the local machine, and the POC uses entirely fictional mock data** — no real member information is ever involved.

---

## 4. The core idea: Retrieval-Augmented Generation (RAG)

If you read one technical section, read this one — it's the heart of the project.

**The analogy:** Imagine asking a brilliant but new analyst to write a query. On their own, they'd guess at table names. But if you first hand them the exact documentation pages for the relevant tables and say *"use only what's on these pages,"* they'll write something correct and tell you which pages they used. RAG does exactly this, automatically, for every question.

**The mechanics, step by step:**

1. **Embed the question.** The user's question ("show each member's active loans and delinquency status") is converted into a list of numbers — an *embedding* — that captures its meaning. We use a dedicated embedding model (`bge-m3`) for this.
2. **Search by meaning (hybrid + rerank).** That embedding is compared against the pre-computed embeddings of every schema-doc chunk in ChromaDB (dense search), and in parallel a **BM25** keyword search runs over the same docs (sparse search). The two ranked lists are fused (Reciprocal Rank Fusion), then a cross-encoder reranker (`bge-reranker-v2-m3`) re-scores the candidates by actual relevance, yielding the **top 5** chunks — e.g., the docs for `members`, `loans`, and `loan_status_history`. Dense search finds "loan_status_history tracks delinquency" even when the question said "delinquency" and the doc said "days past due"; the reranker is what separates the right table from look-alikes at scale.
3. **Build a grounded prompt.** Those retrieved docs are pasted into the prompt as a **Schema Context** block, prefixed with their source filenames, alongside a system instruction that says, in effect: *"Only use tables and columns that appear in this context. If the context doesn't contain the answer, say so — do not guess."*
4. **Generate.** The local LLM writes the SQL plus a short explanation of the join logic and any assumptions.
5. **Cite.** The system attaches the list of source documents it retrieved (`loans.md`, `members.md`, …) to the answer. The analyst can open those exact files to verify the grounding.

**Why this beats the alternatives for us:**

| Approach | Knows our schema? | Stays private? | Stays current? | Verifiable? |
|---|---|---|---|---|
| Public chatbot | ❌ hallucinates | ❌ cloud | n/a | ❌ |
| Fine-tuning on schema | ⚠️ until schema changes | ⚠️ data in weights | ❌ retrain to update | ❌ |
| **RAG (this project)** | ✅ retrieves live docs | ✅ fully local | ✅ re-index, no retrain | ✅ citations |

RAG keeps the sensitive, fast-changing knowledge *outside* the model, in plain files we control. Updating the assistant's knowledge is just re-indexing the docs — seconds, not a retraining run.

---

## 5. How it works, component by component (for engineers)

The project is intentionally split into a **reused, proven ingestion path** and a **hand-rolled, fully transparent query path**. The reasoning: chunk → embed → store is a solved problem, so we use the standard toolchain (LlamaIndex + ChromaDB). The query path (retrieve → prompt → generate → cite → log) is where credibility lives, so every step is explicit and readable rather than hidden behind framework abstractions.

A single function shape, `answer_question(...) -> dict`, is consumed identically by the interactive CLI, the eval harness, and the logger. One function, three callers.

### 5.1 Schema documentation — the knowledge base (`schema_docs/`)

Twenty markdown files, one per table, across **five subject areas**:

- **Member/party:** `members`, `addresses`, `contact_info`, `household_relationships`
- **Deposits:** `accounts`, `account_types`, `transactions`, `holds`
- **Lending:** `loan_applications`, `loans`, `loan_types`, `payment_schedules`, `loan_status_history`
- **Cards:** `card_accounts`, `card_transactions`, `card_rewards`
- **Branch/channel:** `branches`, `staff`, `ref_channel_codes`, `ref_status_codes`

Every doc follows the same structure: a one-line purpose, a columns table (name, type, nullability, description, example value), the primary key, foreign-key relationships, and table-level naming conventions (e.g., *"current address: filter `WHERE end_date IS NULL`"*).

This scope was chosen deliberately to make retrieval *do real work*. Tables within a subject area share vocabulary — both `loans` and `loan_status_history` talk about "loan" and "delinquency" — so the system can't cheat by keyword-matching a unique word. The genuinely hard case, and the clearest demonstration of value, is **cross-subject joins** like "connect member contact info to their active loans," which require retrieving and bridging docs from different areas.

The mock docs are **clearly fictional** and intentionally interchangeable with docs generated from a real warehouse (see §5.7) — the same format feeds the same pipeline.

### 5.2 Ingestion pipeline (`ingest/build_index.py`)

Reads every `.md` file as a single flat document, converts it to an embedding via Ollama's `bge-m3`, and persists it to a ChromaDB collection.

Key parameter choices:
- **One chunk per table doc.** Each `.md` is loaded whole (`CHUNK_SIZE=8192`, overlap 0, **no** markdown-header splitting), so a table's documentation is never split mid-column-list. This is the retrieval-parity requirement with Open WebUI (§5.7 / setup doc): both paths chunk identically.
- **Source metadata** (filename / table name) is attached to every chunk — this is precisely what the citation feature reads back at query time, and the stable key that BM25 + dense fusion join on.

**Rebuild strategy: full wipe and re-embed on every run.** At 20 small docs this takes seconds, and a clean rebuild avoids an entire class of stale-index bugs (a renamed or deleted table lingering as a ghost chunk). If the rebuild produces zero chunks, it raises an error rather than silently leaving an empty index — an empty index is a configuration failure, not a model-quality problem, and should look like one.

### 5.3 The assistant core (`assistant/sql_assistant.py`)

The central `answer_question(question, rag_enabled=True, model="qwen2.5-coder:14b", k=5, ...)` function:

1. **Retrieval (RAG-on only):** hybrid retrieval — dense (Chroma + `bge-m3`) fused with BM25 sparse via RRF, then reranked by `bge-reranker-v2-m3` down to the top-`k` (default 5) chunks; extracts chunk text and **de-duplicated** source filenames. Degrades gracefully to dense-only if the reranker/BM25 deps aren't installed.
2. **Prompt construction:** a system prompt that frames the assistant, forbids inventing names, and *requires* it to decline when the context is insufficient; a Schema Context block of the retrieved chunks (each tagged with its source); and the user's question.
3. **Generation:** via the OpenAI-compatible client pointed at `localhost:11434/v1` (Ollama). The model is configurable; the default is the code-specialized `qwen2.5-coder:14b` — a non-reasoning coder model (the bake-off in §6 evaluated five models; 7b and 14b were statistically tied, and 14b is the operational default for extra headroom on the larger on-prem schema). Reasoning-style models such as `gpt-oss` are detected and run at low reasoning effort so their hidden reasoning channel doesn't exhaust the context window — the coder default needs no such handling, which is why the "no output" bug doesn't occur.
4. **Citation + SQL extraction:** pulls the SQL out of the model's ```` ```sql ```` code block and attaches the citation list. **RAG-off deliberately produces an empty citation list** — that visible difference is itself a demonstrable output.
5. **Returns one dictionary** with: `question`, `rag_enabled`, `sql`, `explanation`, `citations`, `raw_chunks` (full retrieved text, for transparency), `chunk_count`, `latency_ms`, `model`, `timestamp`, and `eval_score`/`eval_reason` (left null for interactive runs, filled in by the eval harness).

A simple interactive **CLI loop** wraps this for ad-hoc use; each interactive query is logged automatically.

### 5.4 The grounding checker (`eval/checker.py`)

A lightweight, dependency-free scorer — no heavyweight SQL parser, which is overkill at this scale. It handles two question types:

**Standard questions** (we know which tables the answer should touch):
- Extract referenced table/column identifiers from the generated SQL with targeted regexes (`FROM`/`JOIN <table>`, `table.column` patterns). It filters out SQL keywords, table aliases, CTE names, derived-table aliases, and schema qualifiers (e.g. `dbo.` / bracket-quoting) so valid SQL is never mis-flagged as referencing a non-existent table.
- **Hallucination check:** does the SQL reference any table that doesn't exist in the schema? If yes → **score 0.0** (this is the failure mode that matters most).
- **Coverage check:** does the SQL reference the tables we expected?
  - All expected tables present → **1.0**
  - Some present, some missing → **0.5**
  - None of the expected tables → **0.0**
- **Prose fallback:** "which table…?" / "what columns…?" lookups are naturally answered in prose, not SQL. If no SQL is produced, expected tables named explicitly in the explanation are credited the same way.

**Trick questions** (the schema genuinely *doesn't* contain what's asked — marked `expected_tables: []`):
- If the model produced SQL anyway → **0.0** (it hallucinated a schema it doesn't have).
- If it produced no SQL *and* explicitly acknowledged the gap ("the schema does not contain…") → **1.0**.
- No SQL but no clear acknowledgment → **0.0**.

The decline-detection uses a curated phrase list (broadened with real model phrasings such as "does not include," "no mention of," "I apologize") and normalizes smart quotes so matching is robust to typography. The checker was **hardened** after the multi-model evaluation revealed it was mis-scoring valid SQL — under-counting correct refusals and flagging schema-qualified names and CTE aliases as hallucinations (§6). It remains a directional signal, not a SQL validator — see §7.

### 5.5 The evaluation harness (`eval/run_eval.py`, `eval/test_questions.yaml`)

This is the project's **primary evidence artifact**. For each of the 15 curated questions it runs the assistant **twice** — once RAG-on, once RAG-off — scores both with the checker, logs both, and writes a side-by-side markdown report (`logs/eval_report.md`) with per-question scores, the delta, the citations, and summary means.

The 15 questions are deliberately mixed:
- **Single-table lookups** (easy — establishes a baseline)
- **Cross-subject joins** (the hard case — where RAG most visibly helps)
- **Trick questions** (3 of them — test whether the model honestly declines instead of inventing tables for investment portfolios, mortgage escrow, or credit-bureau pulls, none of which exist in the schema)

### 5.6 The refresh scheduler (`refresh/refresh_scheduler.py`)

Keeps the index current with zero new dependencies (standard library only). Each cycle:
1. Computes a SHA-256 hash over all schema-doc filenames + contents.
2. Compares it to the last-known hash stored in `logs/refresh_state.json`.
3. **Changed** → rebuild the index, update the stored hash, log `"reindexed"`.
4. **Unchanged** → skip the rebuild, log `"skipped"`.

Two run modes: a **demo mode** (`--interval 120`) that ticks visibly in a terminal for live walkthroughs, and a **`--once` mode** designed to be registered with Windows Task Scheduler (or cron) on a realistic cadence like nightly at 2 AM. The mechanism is intentionally readable as "here's exactly what production would do."

### 5.7 Real-warehouse extraction (`extraction/extract_schema_from_sqlserver.py`)

The bridge from mock to real. It connects to a live MS SQL Server and generates schema docs in the *same format* as the mock ones, querying only **system catalog views**:
- `INFORMATION_SCHEMA.TABLES` / `.COLUMNS` — names, types, nullability
- `sys.foreign_keys` / `sys.foreign_key_columns` — relationships
- `sys.extended_properties` (`MS_Description`) — DBA-authored descriptions where they exist

Two design choices worth calling out for stakeholders:
- **It is strictly read-only.** The script header documents that it needs `SELECT` on catalog views only — **no write access, and no access to any table data or rows.** The first question a DBA asks ("what does this touch?") is answered before it's asked.
- **Documentation gaps are made visible, not hidden.** Where a description is missing, it writes a `<!-- TODO: no description on file -->` placeholder. Grepping for that placeholder produces an instant punch-list of the real warehouse's documentation gaps — a useful side benefit.

The connection string is read from the `SQL_SERVER_DSN` environment variable, never hardcoded. Swapping from mock to real is two commands: run the extractor, then re-run `build_index.py`.

### 5.8 Logging (`logs/`)

Every `answer_question()` call appends one JSON record to `logs/queries.jsonl` (the bulky `raw_chunks` field is omitted to keep the log compact). Each record is a flat, pandas-loadable row: timestamp, question, RAG flag, SQL, explanation, citations, latency, model, and eval score/reason. This makes the whole system **auditable and analyzable** — you can answer "what did it generate, when, grounded in what, and how good was it?" from a single file. The refresh cycle logs similarly to `logs/refresh_log.jsonl`.

---

## 6. Does it actually work? The evidence

The assistant was evaluated across **five local models**, RAG-on vs. RAG-off, scored by the (now hardened — §5.4) grounding checker. Full methodology and the five-model table are in [`docs/EVAL_RESULTS.md`](EVAL_RESULTS.md). The headline from the bake-off (`qwen2.5-coder:7b`, which was statistically tied with the 14b now used as the operational default — a full re-run on the shipped 14b is pending):

| | Mean grounding score (qwen2.5-coder:7b) |
|---|---|
| **RAG enabled** | **0.89** (5-run average; an individual run scored 0.97) |
| No RAG (baseline) | 0.30 |

Rerun `python eval/run_eval.py` to regenerate `logs/eval_report.md` for the current default (`qwen2.5-coder:14b`) and the current hybrid+rerank retrieval config; the report header records exactly which retrieval mode ran.

**What this means in plain terms:** with the schema docs in front of it, the model wrote correctly-grounded SQL — referencing real tables, and the right ones — on essentially every question. Without them, grounding collapsed. The model and the questions were identical in both runs. **Retrieval is the entire difference.**

Some specifics worth highlighting honestly:

- **Cross-subject joins succeeded.** The three-table questions — e.g., "each member's active loans and delinquency status" (`members` + `loans` + `loan_status_history`) and "members with card accounts and their reward points" (`members` + `card_accounts` + `card_rewards`) — scored **1.0** with RAG. These are the hard cases, and they're where RAG most clearly earned its keep.
- **All three trick questions are now scored correctly.** Asked for investment portfolios, mortgage escrow, or credit-bureau pulls — none of which exist — the model declined and acknowledged the gap, scoring **1.0** on each. (An earlier checker version mis-scored two of these as failures purely because their refusal wording wasn't in its phrase list; hardening the checker fixed that — §5.4.)
- **Model choice matters as much as grounding.** The bake-off surfaced a sharp example: an older code-specialized model wrote excellent SQL on real questions yet *hallucinated* SQL for two-thirds of the impossible ones — exactly the dangerous failure RAG is meant to prevent. The chosen model declines reliably (perfect on the trick set) while matching the field's best on real queries.
- **The no-RAG baseline (0.30) isn't a clean zero** — honestly so: without any schema the model still correctly *declines* the trick questions, earning most of those points, but on real questions it has nothing to ground on, which is the whole point.

The system has been exercised heavily: hundreds of query records are logged in `logs/queries.jsonl` across the model bake-off and eval runs, and the ChromaDB index is built and persisted on disk.

---

## 7. Limitations and known gaps (read before drawing conclusions)

We're stating these plainly because an honest POC is more useful than an oversold one.

1. **The grounding checker is approximate** — though hardened. It now strips schema qualifiers, ignores CTE and derived-table aliases, credits prose answers to lookup questions, and recognizes a much broader set of refusal phrasings (an earlier version mis-scored two correct refusals as failures). It is still regex- and phrase-list-based — not a real SQL parser, executor, or semantic-equivalence check — and it checks *table coverage* more rigorously than column-level correctness. It's a strong directional signal, not a certification of correctness.
2. **It drafts; it does not validate.** The assistant produces SQL grounded in the schema, but it does not execute the query, check that it runs, or verify the results are semantically what the analyst wanted. **A human must review every draft.** This is by design — auto-execution is explicitly out of scope (§8).
3. **Quality depends entirely on the docs.** RAG is only as good as the knowledge base. Thin or wrong schema documentation produces thin or wrong SQL. (The extraction script's TODO-placeholder behavior is the first line of defense here.)
4. **Single-machine, single-user scale.** Performance and concurrency for many simultaneous users are unaddressed; this runs on one workstation via Ollama, not a served inference stack.
5. **Small, hand-built test set.** 15 questions is enough to demonstrate the effect convincingly, not enough to be a statistically robust benchmark.
6. **Model dependence.** Results are tied to the local model. The default is `qwen2.5-coder:14b` (statistically tied with the 7b in the five-model bake-off, [`docs/EVAL_RESULTS.md`](EVAL_RESULTS.md)); a different local model shifts the numbers — sometimes sharply, as the bake-off showed.

---

## 8. What this is *not* (explicit scope boundaries)

To prevent over-reading the POC, these were deliberate non-goals:

- **No real member PII or live warehouse data** — fictional mock schema only.
- **No credit, pricing, fraud, or member-facing decisions** — this is an internal SQL-drafting aid, full stop.
- **No auto-execution and no write-back to the database** — the assistant never runs the SQL it writes. Agentic workflows are out of scope.
- **No multi-user serving** — single-analyst workstation.
- **No fine-tuning** — RAG only; sensitive data is never baked into model weights.

---

## 9. Security, privacy, and compliance posture

This is the part leadership and risk should weigh most.

- **Nothing leaves the machine.** Both the embedding model and the LLM run locally via Ollama. There are no external API calls in the query path. Schema details and questions never touch a third-party service.
- **No member data, by design.** The POC uses fictional mock data. The real-warehouse path extracts **only schema metadata** (table/column names, types, relationships, descriptions) — never row-level data.
- **Read-only, least-privilege access to the real warehouse.** The extraction script requires `SELECT` on system catalog views only — documented up front. It cannot modify anything and cannot read table contents.
- **Auditable by construction.** Every query and every refresh is logged to append-only JSON. You can reconstruct exactly what was asked, what was generated, and what it was grounded in.
- **Knowledge stays in files we control.** Because the schema knowledge lives in plain markdown rather than model weights, it can be reviewed, version-controlled, corrected, and deleted at will — and updated without retraining.

---

## 10. How to run it (quick reference)

```powershell
pip install -r requirements.txt

# Prerequisites: Ollama running locally, with models pulled:
#   ollama pull qwen2.5-coder:14b
#   ollama pull bge-m3
# (bge-reranker-v2-m3 is downloaded automatically by sentence-transformers on first use.)

python ingest/build_index.py            # build the index from schema docs
python assistant/sql_assistant.py       # interactive chat
python eval/run_eval.py                 # produce the RAG-on/off comparison report
python refresh/refresh_scheduler.py --interval 120   # demo the refresh loop
```

Pointing at a real warehouse:

```powershell
$env:SQL_SERVER_DSN = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=...;DATABASE=...;UID=...;PWD=..."
python extraction/extract_schema_from_sqlserver.py
python ingest/build_index.py
```

**Testing:** the project ships with a pytest suite (`tests/`) covering the checker, the assistant (with mocked Ollama/Chroma so unit tests need no live model), the ingestion path, and the refresh logic. Integration tests that need a live Ollama are gated behind an `OLLAMA_RUNNING=1` flag so the unit suite runs anywhere.

---

## 11. From POC to production — what would change

If this graduates from proof-of-concept to a real internal tool, the natural progression:

1. **Point at the real warehouse.** Run the extraction script against production catalog views, fill in the TODO-flagged documentation gaps, re-index. The pipeline is already built for this.
2. **Schedule the refresh.** Register `refresh_scheduler.py --once` as a nightly Task Scheduler / cron job so the index tracks schema changes automatically.
3. **Harden the evaluation.** Expand the test set, and replace the regex checker with a proper SQL parser (and ideally a "does it actually execute against a schema?" check) for trustworthy quality metrics.
4. **The team front-end is already chosen: Open WebUI.** The off-the-shelf GUI is wired to the same schema-doc knowledge base over the *already-validated* core — no custom UI to build or maintain. The scripted path and eval harness remain the ground truth for correctness; the GUI is just how it's made pleasant to use. Setup is reproducible from [`docs/OPEN_WEBUI_SETUP.md`](OPEN_WEBUI_SETUP.md).
5. **Consider scale, if needed.** Multi-user serving would mean swapping Ollama for a served inference stack (e.g., vLLM) behind the same OpenAI-compatible front end — only worth it if usage justifies it, and it requires no change to the GUI. See [`docs/PORTING_TO_ONPREM.md`](PORTING_TO_ONPREM.md).
6. **Operational footprint stays modest.** The whole stack is local: the `qwen2.5-coder:14b` code model (~9 GB at Q4_K_M, comfortable on a 16 GB GPU) plus the `bge-m3` embedder and `bge-reranker-v2-m3` reranker on a capable workstation, a few seconds to rebuild a small index, plain files for everything else. No cloud spend, no per-query API cost.

---

## 12. Glossary (for non-technical readers)

- **LLM (Large Language Model):** the AI that generates text/SQL (here, `qwen2.5-coder:14b`).
- **Hallucination:** when an AI confidently produces plausible-sounding but factually wrong output — e.g., inventing a table name.
- **RAG (Retrieval-Augmented Generation):** giving the AI the relevant reference documents *before* it answers, so it grounds its response in real facts instead of guessing.
- **Embedding:** a numeric representation of a piece of text's meaning, used to find semantically similar text.
- **Vector store / ChromaDB:** a database that stores embeddings and finds the closest matches to a query — search by meaning, not keywords.
- **Grounding:** answering using verifiable source material rather than the model's general training.
- **Citation:** the list of source documents the assistant used, so a human can check the work.
- **Ollama:** software that runs AI models locally on your own machine instead of in the cloud.
- **Schema:** the structure of a database — its tables, columns, and how they relate.

---

## 13. Bottom line

We set out to prove a specific, falsifiable claim: *that a fully local AI, grounded in our own schema documentation via retrieval, can draft accurate, verifiable SQL — without sending anything to the cloud and without baking sensitive data into a model.*

The evidence supports it. With retrieval, the assistant grounded its answers correctly on essentially all of a representative test set (**0.89**, 5-run average), including the hardest cross-subject joins; without it, grounding collapsed (**0.30**, much of it from correct refusals). Every answer is cited and every run is logged, so the grounding is verifiable rather than taken on faith. The path to a real warehouse is already built and is strictly read-only, metadata-only.

It is a proof-of-concept with honest limitations — it drafts rather than validates, its automated scorer is approximate, and it runs at single-analyst scale. But it demonstrates the core mechanism convincingly and safely, and it lays out a clear, low-risk path from here to a useful internal tool.
