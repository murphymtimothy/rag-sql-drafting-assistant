# Handoff: Refactor the local RAG SQL-Drafting Assistant

## 0. How to use this prompt

Paste this whole document into Cowork as the kickoff prompt for a refactor session on my existing project repo. First **read the existing codebase and orient yourself**, then propose a short plan back to me before making sweeping changes. Preserve everything that already works; only change what Sections 3–4 call for. Work on a branch.

---

## 1. Context & the real goal

This is a **local, fully offline SQL-drafting assistant** grounded via RAG over data-warehouse **schema documentation**. Given an analyst's natural-language question, it retrieves the relevant table docs, hands them to a local LLM as reference, drafts a SQL query, and **cites the exact schema docs it used** so a human can verify the grounding instead of trusting it.

**North star (this matters — let it shape every decision):** This home build on my personal PC is a rehearsal for a proof-of-concept I will build at **Redwood Credit Union**, where we are **on-prem, run Microsoft SQL Server (T-SQL)**, and work with **hundreds of tables — some with hundreds of columns and millions of rows**. The eventual work POC will run against the real schema (never mock data) and is meant to show a team of ~5 analysts/engineers and leadership what a **local LLM in a regulated enterprise environment** can do. So the home version must (a) actually ground correctly, and (b) port cleanly to on-prem MS SQL Server at much larger schema breadth.

**Hard constraints:**
- Fully local / offline. No cloud APIs, no data leaves the machine.
- Mock/fictional schema data only at home. Never real member data.
- Target SQL dialect is **Microsoft SQL Server / T-SQL**.
- The team GUI must be **off-the-shelf** — I do **not** want to build or maintain a custom front end.

**My hardware (home):** Ryzen 7 9800X3D, 32 GB DDR5, **RTX 5080 (16 GB VRAM)**, 2 TB NVMe, Windows. The 16 GB VRAM is the only real constraint.

---

## 2. Current state — orient before changing anything

Existing stack: **Ollama** (local inference) · **LlamaIndex** (ingestion) · **ChromaDB** (vector store) · **OpenAI Python SDK pointed at Ollama** · Python 3.11+. Expected repo layout (verify against what's actually there):

```
schema_docs/    Mock warehouse schema docs (~20 tables, 5 subject areas), one markdown file per table
ingest/         build_index.py — chunk -> embed -> persist to Chroma
assistant/      sql_assistant.py — retrieval + prompting + citations + CLI (answer_question())
eval/           checker.py, test_questions.yaml, run_eval.py — grounding eval harness
refresh/        refresh_scheduler.py — hash-detect + reindex
extraction/     extract_schema_from_sqlserver.py — real MS SQL Server -> schema docs
logs/           queries.jsonl, refresh_log.jsonl (gitignored)
tests/          pytest unit + integration tests
```

**Two known problems to fix:**
1. **"No output" sometimes** in the GUI — this was a *thinking-model* failure mode (reasoning models like gemma3 / gpt-oss going blank). The fix is using a non-thinking coder model; do **not** chase reasoning models.
2. **"Totally wrong SQL"** — this is a *retrieval/grounding* failure, not a model-quality problem. The fix is in retrieval config and the system prompt (Sections 3–5), not a bigger model.

---

## 3. Target architecture (the overhaul)

| Layer | Decision |
|---|---|
| Inference engine | **Keep Ollama.** Always-on, self-hostable, ports straight to on-prem. |
| Team GUI | **Adopt Open WebUI as the front end. Embrace it; do not build a custom UI.** Off-the-shelf, multi-user, persistent knowledge bases, model import/config from the UI, self-hostable on-prem via Docker. |
| LLM | **`qwen2.5-coder:14b`** — non-thinking coder (this alone kills the "no output" bug), fits 16 GB at Q4_K_M (~9 GB) with headroom. |
| Embedder | **`bge-m3`** (sparse+dense, pairs well with hybrid search at scale); `nomic-embed-text` acceptable fallback. |
| Vector store | **Keep ChromaDB** for the scripted pipeline. (Corpus is tiny — schema docs only — so this is not load-bearing.) |
| Scripted pipeline | **Keep as the validated ground-truth core.** It is NOT the user-facing app; it is the thing the eval proves correct and the reference retrieval implementation. |
| Eval harness | **Keep and harden — this is the evidence layer** (Section 4.7). The ONLY custom non-GUI piece. Run on demand, no service. |

**Key framing for the refactor:** the Open WebUI configuration (chunking, Top-K, hybrid search, reranker) is **the actual enterprise skill being rehearsed**, not incidental complexity. At ~20 mock tables it barely matters; at Redwood's hundreds of tables, retrieval is the whole ballgame. Tune it deliberately and document it.

---

## 4. Work items

### 4.1 Orient & branch
Read the repo. Confirm the layout in Section 2. Create a working branch. Summarize back to me what you found and your concrete plan before large edits.

### 4.2 Models
- Make **`qwen2.5-coder:14b`** the default model everywhere (replace any `:7b` / gemma3 / gpt-oss defaults in code, config, and docs).
- Make **`bge-m3`** the default embedding model (replace `nomic-embed-text` defaults, but keep it selectable as a fallback).
- Update the README prerequisites/pull commands accordingly (`ollama pull qwen2.5-coder:14b`, `ollama pull bge-m3`).

### 4.3 Scripted pipeline (the validated core)
- Ensure `assistant/sql_assistant.py` uses the **T-SQL grounding system prompt** from Section 5.1 verbatim.
- Confirm `answer_question()` returns SQL + explanation + **citations** (list of source schema-doc filenames) and that every call is appended to `logs/queries.jsonl` (Section 5.4 schema).
- Keep the CLI working as the scripted entry point.

### 4.4 Retrieval tuning + parity with Open WebUI
The scripted pipeline and Open WebUI are two retrieval implementations; they must behave equivalently so the eval is a faithful proxy for the GUI. Align both to:
- **One chunk per table doc** (do not split a table's documentation across chunks). In LlamaIndex, set chunking so a typical table doc stays whole; turn off markdown-header-based splitting.
- **Top-K = 5.**
- **Hybrid (dense + sparse) retrieval** with a **reranker: `bge-reranker-v2-m3`**. Add the reranker to the Python path too (or document precisely why the eval's retrieval is equivalent without it).
- Document the parity in the README so it's clear the eval reflects what the GUI does.

### 4.5 T-SQL grounding system prompt
Apply the prompt in Section 5.1 in both the scripted pipeline and the Open WebUI model config.

### 4.6 Open WebUI setup — documented & reproducible
Create `docs/OPEN_WEBUI_SETUP.md` capturing the exact, reproducible configuration in Section 5.2 / 5.3 (settings, knowledge-base creation, model creation, system prompt, how to scope a chat with `#`). This is config, not code, but it must be reproducible by a teammate from scratch.

### 4.7 Eval harness (the evidence layer — most important deliverable)
This is what turns a cool demo into a credible POC in a regulated environment. Harden `eval/`:
- For each curated question, run `answer_question()` **with RAG on and with RAG off**; capture SQL + citations + latency.
- Checker (`eval/checker.py`): parse generated SQL for referenced table/column identifiers; **strip `dbo.` and T-SQL `[ ]` bracket-quoting**; **ignore CTE names and derived-table aliases** (don't flag them as hallucinated); **credit prose answers** to "which table/what columns" lookups; recognize a broad set of **refusal phrasings**. Score each answer on: references only real tables/columns AND includes the expected ones.
- Output **`logs/eval_report.md`** — a side-by-side RAG-on vs RAG-off table with per-question scores and an average grounding score.
- No UI. Runs on demand: `python eval/run_eval.py`. Keep/extend `tests/test_checker.py` regression tests so scores stay trustworthy.

### 4.8 Docs update + porting notes
- Update README to reflect the new stack (Ollama + Open WebUI + `qwen2.5-coder:14b` + `bge-m3`) and the home→Redwood narrative.
- Add a short `docs/PORTING_TO_ONPREM.md` covering Section 8.

### 4.9 Cleanup
- Remove any half-built custom front-end code/ambitions (the GUI is Open WebUI now).
- Keep `extraction/extract_schema_from_sqlserver.py` first-class — it is the bridge to the real warehouse. Ensure it remains **read-only, system-catalog/metadata-only** (no table-data access, no writes).

---

## 5. Assets to bake in

### 5.1 T-SQL grounding system prompt (use verbatim)

```
You are a SQL-drafting assistant for analysts at a credit union. You draft Microsoft SQL Server (T-SQL) queries for a human to review and run. You do not execute SQL.

Grounding rules:
- Use ONLY the tables and columns that appear in the provided Schema Context. Never invent table or column names.
- If the Schema Context does not contain what is needed, say so plainly and do not guess. Name what additional table docs you would need.
- Draft read-only queries (SELECT) unless explicitly asked otherwise. Do not emit INSERT/UPDATE/DELETE/DDL by default.

Dialect rules (Microsoft SQL Server / T-SQL only):
- Use T-SQL syntax: TOP (not LIMIT), GETDATE()/SYSDATETIME() (not NOW()), EOMONTH(), ISNULL()/COALESCE(), OFFSET/FETCH for paging, and [bracket] quoting for identifiers.
- Do NOT use MySQL- or Postgres-only syntax (no LIMIT, no backticks, no NOW(), no ILIKE).

Output:
- Provide the SQL, then 2-3 sentences explaining the join logic and any assumptions.
- End every answer by listing the schema doc(s) you used as citations.
```

### 5.2 Open WebUI — document/RAG settings (Admin Panel → Settings → Documents)
- Embedding Model Engine: **Ollama**; Embedding Model: **`bge-m3`**.
- Text splitter: **Token**; chunk size set large enough that a typical table doc stays in **one chunk**; **markdown-header splitting OFF**.
- **Top K: 5.**
- **Hybrid search: ON.**
- **Reranking model: `bge-reranker-v2-m3`.**
- Then: Workspace → Knowledge → **+ Create Knowledge Base** named `Schema Docs`; upload all `schema_docs/*.md`. Re-upload/reindex whenever the docs change.

### 5.3 Open WebUI — model settings (Workspace → Models)
- Create a model on base **`qwen2.5-coder:14b`**.
- System prompt: paste Section 5.1 verbatim.
- Attach the `Schema Docs` knowledge base.
- Context length: ≥ 8192.
- Note: `qwen2.5-coder` is non-thinking, so the empty-output bug does not apply. If anyone ever loads a *reasoning* base model, set the `think (Ollama)` toggle **Off on the base model** (it is unreliable on custom Workspace models).
- Usage: in a chat, scope retrieval by typing `#Schema Docs`.

### 5.4 `logs/queries.jsonl` record schema (one JSON object per `answer_question()` call)
```
timestamp, question, rag_enabled, sql, explanation, citations[], latency_ms, model, eval_score, eval_reason, chunk_count
```
(`eval_score`/`eval_reason` are null for interactive, non-eval runs.)

---

## 6. Acceptance criteria
1. The "no output" failure is gone (coder model in use; verified in both CLI and Open WebUI).
2. `python eval/run_eval.py` produces `logs/eval_report.md` with a clear **RAG-on vs RAG-off** grounding comparison, every answer cited, and a meaningfully higher score with RAG on.
3. In Open WebUI, asking a representative question against `#Schema Docs` returns **grounded T-SQL with citations** to the correct table docs.
4. The scripted pipeline's retrieval config matches the Open WebUI config (Section 4.4), documented in the README.
5. Setup is reproducible by a teammate from `docs/OPEN_WEBUI_SETUP.md` and the README alone.
6. All tests pass.

---

## 7. Non-goals / guardrails (do NOT do these)
- **No custom front end.** Open WebUI is the GUI.
- **No cloud anything.** Fully local/offline.
- **No fine-tuning.** Grounding is via retrieval; keep schema out of model weights.
- **No reasoning/"thinking" models** as the default.
- **No vLLM / heavyweight serving** at home (note it only as a future on-prem option — Section 8).
- **Do not over-engineer retrieval** beyond Section 4.4 unless an eval failure demonstrates the need.
- **Mock data only** at home; never wire up real member data.

---

## 8. Home → Redwood (on-prem) porting notes
- **The millions of rows are irrelevant to the RAG.** We never embed row data — only schema docs. What scales is *schema breadth* (hundreds of tables × hundreds of columns ≈ a few thousand schema chunks), which is a modest retrieval corpus.
- The real enterprise difficulty is **disambiguation**: many similar tables/columns and many plausible join paths. The reranker + well-written **FK/relationship sections** in each table doc are the levers that solve this — invest in doc quality there.
- `extraction/extract_schema_from_sqlserver.py` is the bridge: at work it regenerates `schema_docs/` from the real catalog (read-only, metadata-only). Keep it clean and central.
- Scaling paths that need NOTHING at home but should remain architecturally open: if Open WebUI's built-in RAG hits a ceiling, plug a custom retrieval backend behind it via **Open WebUI Pipelines/Functions** (the team's UI never changes); if 5 concurrent users strain Ollama, swap **vLLM** behind the same OpenAI-compatible front end. Don't build either now.
