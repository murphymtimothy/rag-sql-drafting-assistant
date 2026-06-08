# SQL-Drafting Assistant POC — Design Spec

**Date:** 2026-06-07
**Author:** Data scientist (Credit Union)
**Status:** Approved — ready for implementation planning

---

## Overview

A local, fully offline SQL-drafting assistant grounded via RAG over a mock credit-union data warehouse schema. Built to satisfy four explicit success criteria — grounded/correct SQL, source citations, visibly better than no-RAG baseline, and logged/repeatable runs — in a form narrow enough to get approved quickly and defensible enough to show to stakeholders.

The POC is a learning artifact *and* an evidence base: every run is logged, a batch eval harness produces a side-by-side RAG-on/off comparison report, and an automated schema-refresh pipeline keeps the knowledge base current. All compute stays on the local machine; nothing touches real member data.

---

## Goals & success criteria

| Criterion | What it looks like at the end |
|---|---|
| Grounded, correct SQL | Generated SQL references real table/column names from schema docs — not hallucinated ones — and reflects documented join paths |
| Source citations | Every answer includes the schema doc(s) it retrieved from, so grounding can be verified rather than trusted |
| Visibly better than no-RAG | `run_eval.py` produces a side-by-side RAG-on/off report with automated grounding scores over a curated 12-15 question test set |
| Logged & repeatable | Every query (interactive and eval) is appended to `logs/queries.jsonl` in a structured format loadable into pandas |

---

## Non-goals (explicit scope boundaries)

- No real member PII or actual warehouse data — mock schema only for the POC
- No credit, pricing, fraud, or member-facing decisions — internal SQL-drafting tool only
- No multi-user serving — single analyst workstation (Ollama, not vLLM)
- No fine-tuning — RAG only; sensitive data never baked into model weights
- Agentic workflows (auto-executing generated SQL, writing back to DB) are explicitly out of scope

---

## Architecture approach

**Hybrid:** LlamaIndex + ChromaDB for ingestion (reuses the proven pattern from the personal setup guide §13), hand-rolled retrieval/prompt/generation/citation/logging for full transparency and eval instrumentation.

Rationale: the ingestion side (chunk → embed → persist) is a solved problem; reusing the established toolchain avoids re-deriving it. The query side (retrieval → prompt construction → generation → citation extraction → logging) needs to be fully transparent so every step can be narrated to a reviewer — framework abstractions would obscure exactly the pieces that matter most for the POC's credibility.

---

## Project layout

```
poc-sql-assistant/
  schema_docs/                         # mock warehouse docs (markdown, 15-20 tables)
  extraction/
    extract_schema_from_sqlserver.py   # real-DB → markdown doc generator (pyodbc/SQLAlchemy)
  ingest/
    build_index.py                     # chunk → embed → persist to Chroma
  assistant/
    sql_assistant.py                   # retrieval + prompt + generation + citations + logging
  eval/
    test_questions.yaml                # curated Q set, annotated with expected tables/columns
    checker.py                         # automated grounding checker
    run_eval.py                        # batch RAG-on/off comparison runner + report generator
  refresh/
    refresh_scheduler.py               # extract → hash-check → reindex on a configurable interval
  logs/
    queries.jsonl                      # append-only structured query/response log
    refresh_log.jsonl                  # append-only refresh cycle log
    refresh_state.json                 # last-known content hash (used by change detection)
```

---

## Section 1: Mock data warehouse schema docs

**Scope:** 15-20 tables across five subject areas, hand-authored as clearly fictional (no resemblance to any real institution's schema).

**Subject areas:**
- **Member/party:** members, addresses, contact_info, household_relationships
- **Deposits:** accounts, account_types, transactions, holds
- **Lending:** loan_applications, loans, loan_types, payment_schedules, loan_status_history
- **Cards:** card_accounts, card_transactions, card_rewards
- **Branch/channel:** branches, staff, ref_channel_codes, ref_status_codes

**Doc structure per table (consistent across mock and real-extracted docs — they're interchangeable inputs):**

```markdown
# TABLE: <table_name>

**Subject area:** <area>
**Purpose:** <one-sentence description>

## Columns

| Column | Type | Nullable | Description | Example |
|---|---|---|---|---|
| member_id | INT | NOT NULL | Primary key, surrogate member identifier | 10042 |
...

## Primary key
<pk definition>

## Foreign keys / relationships
- `member_id` → `members.member_id`
- ...

## Naming conventions
<any table-level conventions worth noting>
```

**Why this scope produces meaningful retrieval:** tables within a subject area share vocabulary (e.g., both `loans` and `loan_status_history` reference "loan" and "delinquency"), so the retrieval has to do real work — it can't answer "which table tracks delinquency?" by keyword-matching on a unique word. Cross-subject questions (e.g., "join member contact info to their active loans") are the genuinely hard case and the clearest demonstration of grounding value.

---

## Section 2: Extraction script (real MS SQL Server → schema docs)

**File:** `extraction/extract_schema_from_sqlserver.py`

**Queries:**
- `INFORMATION_SCHEMA.TABLES` / `.COLUMNS` — table names, column names, data types, nullability
- `sys.foreign_keys` / `sys.foreign_key_columns` — FK relationships between tables
- `sys.extended_properties` (`MS_Description`) — prose descriptions where populated by DBAs

**Output:** one `.md` file per table, using the same structure as the mock docs. Swapping mock → real schema is: run this script against the warehouse, re-run `build_index.py`.

**Key behaviors:**
- Missing extended-property descriptions emit a clearly-marked placeholder (`<!-- TODO: no description on file -->`), never silently produce a thin doc. As a side effect, grepping for this placeholder produces a punch list of documentation gaps in the real warehouse.
- Script header documents that it requires **read-only** `SELECT` on system catalog views only — no write access, no access to table data/rows. Stated explicitly so the first DBA question ("what does this touch?") is already answered.
- Connection string is read from an environment variable (`SQL_SERVER_DSN`), never hardcoded.

---

## Section 3: Ingestion pipeline

**File:** `ingest/build_index.py`

**Stack:** flat per-file `Document` load → `OllamaEmbedding` (`bge-m3`) → `ChromaVectorStore` (persistent).

**Key parameters:**
- **One chunk per table doc:** each `.md` is loaded as a single flat document (`CHUNK_SIZE=8192`, overlap 0, **no** markdown-header splitting), so a table's documentation is never split mid-column-list. This is the retrieval-parity requirement with Open WebUI.
- **Source metadata:** doc filename and table name preserved on every chunk — this is what the citation feature reads back at query time, and the stable key BM25 + dense fusion join on.

**Rebuild strategy:** full wipe and re-embed on every invocation. At 15-20 small docs this takes seconds, and full rebuild avoids stale-chunk bugs (renamed/deleted tables lingering in the index) that incremental approaches introduce.

---

## Section 4: The assistant core

**File:** `assistant/sql_assistant.py`

**Core function:** `answer_question(question: str, rag_enabled: bool) -> dict`

**Steps:**

1. **Retrieval (RAG-on only):** hybrid — embed the question using `bge-m3` and query Chroma for dense candidates; in parallel run BM25 sparse search over `schema_docs/`; fuse the two ranked lists via Reciprocal Rank Fusion; rerank with the `bge-reranker-v2-m3` cross-encoder down to top-k (k=5, configurable); extract chunk text and source metadata. Degrades to dense-only if BM25/reranker deps are absent.
2. **Prompt construction:**
   - **System prompt:** frames the assistant as a SQL-drafting assistant for the credit union warehouse; explicitly instructs it to reference only tables/columns in the provided schema context; explicitly instructs it to say so if it cannot answer from the context rather than guessing (that "say so" instruction is itself an eval target). It also carries the T-SQL dialect rules, a set of **query-correctness patterns** for analytic shapes that fail subtly (latest-row-per-entity with a tiebreaker, reading running-balance/ledger columns without MAX/SUM, the period-over-period reduce-then-LAG sequence, and fan-out-aware joins), and a final self-check that every referenced table, column, and alias is defined. The full text is `SYSTEM_PROMPT` in `assistant/sql_assistant.py`, kept verbatim in the Open WebUI model config.
   - **Context block (RAG-on):** retrieved chunk texts, formatted with their source table names.
   - **User turn:** the question.
3. **Generation:** via the OpenAI-compatible client (`localhost:11434/v1`), requesting SQL + a short explanation of join logic/assumptions. Model is configurable (defaults to `qwen2.5-coder:14b`; the five-model bake-off found 7b and 14b statistically tied, and 14b is the operational default for on-prem headroom — see `docs/model-selection.md`). The system prompt is the verbatim Section 5.1 T-SQL grounding prompt; reasoning-style models such as `gpt-oss` are run at low reasoning effort so their hidden reasoning channel doesn't exhaust the context window.
4. **Citation extraction:** source table names and filenames from retrieved chunks, attached to the result. RAG-off produces an empty citation list — this difference is itself a visible, demonstrable output.
5. **Return value:**
   ```python
   {
     "question": str,
     "rag_enabled": bool,
     "sql": str,
     "explanation": str,
     "citations": list[str],          # ["loans.md", "members.md"] or []
     "raw_chunks": list[str],         # full text of retrieved chunks, for transparency
     "latency_ms": int,
     "model": str,
     "timestamp": str,                # ISO 8601
   }
   ```

This single return shape is consumed identically by the interactive CLI, the eval harness, and the logger — one function, multiple callers.

---

## Section 5: Eval harness

### `eval/test_questions.yaml`

12-15 curated questions, each annotated:

```yaml
- question: "Write a query showing each member's active loans and their current delinquency status."
  expected_tables: [members, loans, loan_status_history]
  expected_columns: [member_id, loan_id, status_cd]
  notes: "Cross-subject join. Tests whether retrieval bridges member and lending areas."

- question: "Which table tracks card reward point balances, and how does it relate to the member?"
  expected_tables: [card_rewards, card_accounts, members]
  expected_columns: [member_id, card_account_id, points_balance]
  notes: "Multi-hop relationship: rewards → card_accounts → members."
```

Question types included:
- Single-table lookups (easy — establishes baseline)
- Cross-subject joins (the genuinely hard case — where RAG most visibly helps)
- "Trick" questions referencing things not in the schema (2-3 of these — tests "say so" compliance)

### `eval/checker.py`

Lightweight SQL grounding checker. Two evaluation paths depending on question type:

**Standard questions** (have `expected_tables` populated):
1. Extract referenced table/column identifiers (regex or lightweight tokenizer — no full AST parser needed at this scale)
2. Check **(a)** every referenced table/column exists in the mock schema → catches hallucination
3. Check **(b)** the referenced set overlaps with `expected_tables`/`expected_columns` → catches "valid SQL, wrong answer"
4. Score: **1.0** = all expected tables/columns present and no hallucinated names; **0.5** = expected tables partially matched (some found, some missing); **0.0** = hallucination detected or no expected tables matched

**Trick questions** (`expected_tables: []` in YAML — the schema doesn't contain what's asked):
1. Detect whether SQL was generated at all — if the model produced SQL anyway, that's a failure (it should have said "I can't find that in the schema")
2. If no SQL: check whether the response contains an explicit "I cannot answer from the provided schema" acknowledgment
3. Score: **1.0** = no SQL generated, explicit acknowledgment; **0.0** = SQL generated anyway (hallucinated schema) or neither SQL nor acknowledgment

Edge case: unparseable SQL → score=0, reason="unparseable", run continues (one bad answer does not abort the batch).

### `eval/run_eval.py`

For each question in `test_questions.yaml`:
1. Call `answer_question(q, rag_enabled=True)` → score with checker
2. Call `answer_question(q, rag_enabled=False)` → score with checker
3. Append both records to `logs/queries.jsonl` with `eval_score` and `eval_reason` populated

Output: a markdown table (RAG-on score, RAG-off score, delta, citations) + summary stats (mean grounding score RAG-on vs. off across all questions). This is the primary artifact for "visibly better than no-RAG."

---

## Section 6: Logging

**`logs/queries.jsonl`** — one JSON record per `answer_question()` call, appended:

```json
{
  "timestamp": "2026-06-07T14:03:22Z",
  "question": "...",
  "rag_enabled": true,
  "sql": "...",
  "explanation": "...",
  "citations": ["loans.md", "members.md"],
  "latency_ms": 1840,
  "model": "qwen2.5-coder:14b",
  "eval_score": 1.0,
  "eval_reason": "All expected tables and columns present",
  "chunk_count": 5
}
```

`eval_score` / `eval_reason` are `null` for interactive (non-eval) runs.

**`logs/refresh_log.jsonl`** — one record per refresh cycle:

```json
{
  "timestamp": "2026-06-07T14:00:00Z",
  "action": "reindexed",
  "tables_found": 18,
  "docs_changed": 3,
  "duration_ms": 4200
}
```

`action` is `"skipped"` (no changes) or `"reindexed"` (changes detected). Paired with `logs/refresh_state.json` which stores the last-known content hash.

---

## Section 7: Refresh scheduler

**File:** `refresh/refresh_scheduler.py`

**Cycle:**
1. Run extraction (always) → regenerate `schema_docs/*.md`
2. Compute SHA-256 hash of the `schema_docs/` folder contents
3. Compare to hash stored in `logs/refresh_state.json`
4. If changed → rebuild index (`build_index.py` logic), update stored hash, log `"reindexed"`
5. If unchanged → skip rebuild, log `"skipped"`

**Two run modes:**
- **Demo mode** (`--interval 120`): runs in the foreground with a configurable short interval (default 2 minutes). Use during walkthroughs — visible ticking in a terminal window, fast enough to show a live schema-change being picked up.
- **Scheduled (Task Scheduler):** same script registered as a Windows Task Scheduler job on a realistic cadence (e.g., nightly 2 AM). Guide documents both the Task Scheduler setup steps and the equivalent cron syntax for Linux, so the POC's mechanism is directly readable as "here's what production would do."

**Implementation:** stdlib only — `time.sleep` loop, `hashlib`, `subprocess` or direct function call for extraction/indexing. No new scheduler dependency.

---

## Section 8: Open WebUI integration

Open WebUI is the **off-the-shelf team GUI** (not a custom front end), wired to the same `schema_docs/` folder via its "Knowledge" feature. The full, reproducible configuration lives in [`OPEN_WEBUI_SETUP.md`](OPEN_WEBUI_SETUP.md); in brief, to match the scripted pipeline's grounding quality:

- **Admin Panel → Settings → Documents:** embedding engine **Ollama** / `bge-m3`; **Token** text-splitter, chunk size large enough that a table doc stays in **one chunk**, markdown-header splitting **off**; **Top K 5**; **hybrid search ON**; reranking model **`bge-reranker-v2-m3`**. **Replace the default RAG Template** with the neutral, grounding-consistent one in `OPEN_WEBUI_SETUP.md` §1 — the stock template licenses answering from outside knowledge and silently undermines grounding. Then create the `Schema Docs` Knowledge Base and upload the docs. Re-upload + reindex whenever `schema_docs/` changes.
- **Workspace → Models:** create a model on **`qwen2.5-coder:14b`**, paste the verbatim Section 5.1 grounding system prompt, attach the Knowledge Base, and set context length ≥ 8192. Scope a chat with `#Schema Docs`.

This provides a conversational GUI layer for interactive use or demos.

This is explicitly a **thin presentation layer** on top of the already-validated core, not a parallel pipeline. The scripted path and eval harness are the ground truth for correctness; WebUI is how it's made pleasant to use. The guide makes this distinction explicit — a natural answer to "which version is the real one?"

---

## Section 9: Error handling

| Failure | Behavior |
|---|---|
| Ollama unreachable | Fail loudly — no silent fallback |
| Chroma index missing in RAG mode | Clear error: "run `build_index.py` first" — does not silently behave like RAG-off |
| Unparseable generated SQL in eval | Score=0, reason="unparseable", run continues |
| SQL Server connection failure in extraction | Surface the actual driver error — "what exactly broke" is what a DBA will ask first |
| Missing env var (`SQL_SERVER_DSN`) | Fail with an explicit "set `SQL_SERVER_DSN` environment variable" message |
| Chroma empty after build | Warn and surface chunk count — zero chunks is a configuration error, not a model quality issue |

---

## Definition of done

The POC is complete when:

- [ ] `run_eval.py` produces a side-by-side RAG-on/off markdown report with automated grounding scores over all 12-15 test questions
- [ ] `logs/queries.jsonl` and `logs/refresh_log.jsonl` exist and are populated from real runs
- [ ] `refresh_scheduler.py` is running and demonstrably picks up a schema doc change (detected, reindexed, new answer reflects the change)
- [ ] Open WebUI is wired to the same `schema_docs/` Knowledge Base and returns grounded answers in the browser
- [ ] The extraction script is ready to point at a real SQL Server instance (documented connection string, confirmed read-only permission requirements)
