# Handoff: §3b — Schema-Linking Retrieval

**Date:** 2026-06-08
**Status:** HANDOFF / NOT YET DESIGNED — start the next session here. Begin with `superpowers:brainstorming` (this doc is the starting brief, not a finalized spec).
**Roadmap item:** §3b — make retrieval reliably surface the right tables/columns regardless of question phrasing.

---

## Where we are (end of 2026-06-08)

- **§2d + §3a are done, merged to `main`, and pushed.** The deterministic validator (`validate_sql`) runs inside `answer_question()` (PR #8) *and* in the GUI via the new local OpenAI-compatible API (`serve/` package, §3a). Open WebUI now drives the **same** pipeline as the scripted path — one source of truth.
- **Hallucination-on-generation is solved.** The model can no longer ship SQL referencing tables/columns it wasn't given; the validator catches unknown columns, non-T-SQL dialect, and invalid `status_cd` enums before the analyst sees them.
- The §3a design + decisions are in `docs/specs/2026-06-08-openwebui-local-api-design.md`. Read it for context on the serve layer and deployment (Ollama native on host, host process, bearer auth).

## The problem §3b solves (with today's live repro)

The validator runs **after** generation — it cannot surface a table the **retriever** never fetched. Observed in the GUI today:

| Question | Retrieval | Result |
|---|---|---|
| "How many members joined in the last year?" | `members.md` retrieved | ✅ correct grounded query on `members.member_since_date` |
| "Tell me our member gains and losses over the last year and the net growth." | `members.md` **NOT** retrieved | ❌ model truthfully said *"no members table in my context"* and declined |

**Root cause:** top-K (=5) **doc-level** retrieval drops the needed table when the question's wording doesn't lexically/semantically match the table doc. "gains / losses / net growth" doesn't match `members.md` (which talks about `member_since_date`, `status_cd`), so the reranker ranked other docs above it and `members.md` fell outside the top-5. The model then safely declined — **better than the original hallucination, but still wrong**: gains *are* derivable from `members.member_since_date`; losses/net-growth are *not* (no member-departure date exists anywhere in the schema).

At Redwood's hundreds of tables, this retrieval-coverage gap is the **dominant** failure mode.

## Goal

Reliably surface the tables/columns a question needs into the model's Schema Context **regardless of phrasing**, **without** overflowing Ollama's context window (`num_ctx` is tight — raising K indiscriminately has previously caused empty-output truncation). Precision, not just more recall.

## Current retrieval architecture (what to build on)

- **`assistant/sql_assistant.py` → `_retrieve()`**: `_dense_search` (Chroma vectors via `bge-m3`) + `_sparse_search` (BM25 over `schema_docs`) → `_rrf_fuse` (Reciprocal Rank Fusion) → `_rerank` (`bge-reranker-v2-m3` cross-encoder) → **top-K = 5** chunks. One chunk per table doc (`CHUNK_SIZE = 8192`). The cross-encoder is the precision knob.
- Multi-turn (§3a) already combines the **last ~2 user messages** as the retrieval query (`_retrieval_query`).
- **`assistant/validate.py` → `build_catalog()`** already parses every `schema_docs/*.md` into `{table: {column: type}}` — a ready foundation for column/FK extraction (reuse it, don't re-parse).
- **`schema_docs/*.md`** each have **machine-parseable** FK sections: `**Outbound ...**` (``col`` → ``table.col``) and `**Referenced by ...**`. (Verified parseable earlier this project.) `**Common join paths**` is prose. `ref_status_codes.md` / `ref_channel_codes.md` hold the enum domains.

## Candidate approaches (brainstorm + decide next session)

1. **FK-graph expansion (cheapest high-value).** Build a table-level FK graph from the Outbound/Referenced-by sections; after initial retrieval, pull in FK-neighbors of retrieved tables (e.g. `members`↔`loans`↔`loan_status_history`). Deterministic, no extra LLM call, guarantees join targets are present.
2. **Column-/entity-aware retrieval (the deeper fix).** Index column names + descriptions (not just table docs) and/or maintain a term→table map with synonyms (e.g. "joined"→`member_since_date`, "delinquency"→`loan_status_history.days_past_due`). Surfaces a table via its *columns* even when the doc prose doesn't match the question.
3. **Inject join paths + enum domains into the prompt.** Once tables are linked, add the relevant FK edges (the linking columns) and the valid `ref_status_codes` values for any in-scope `status_cd` directly to the Schema Context — so the model has the join keys and valid literals up front.
4. **Two-stage schema linking (DIN-SQL/CHESS-style).** A cheap first pass (deterministic keyword match or a small LLM call) names the tables/columns the question needs; retrieve those precisely. More moving parts; revisit if 1–3 fall short.
5. **Retrieval-query expansion.** Hypothetical-document or keyword expansion before embedding (e.g. expand "gains/losses/net growth" → "members joining and leaving, member_since_date, membership status").

**Recommended starting bet:** #1 (FK-graph expansion) + #3 (inject join paths/enums) are the cheapest, most deterministic wins and directly fix today's repro. #2 is the deeper investment for Redwood scale. Decide in brainstorming.

**Constraints:** keep `num_ctx` from overflowing (prefer precise retrieval over a bigger K); on-prem/offline; the scripted path and the GUI both call `_retrieve`, so any change benefits both automatically (don't fork them).

## "Done" looks like

- The repro query — *"member gains and losses over the last year and net growth"* — surfaces `members.md` **without naming the table in the prompt**, and yields the correct answer: derivable **gains** (`members.member_since_date`) + an explicit **"losses/net-growth not derivable"** (no departure date).
- A **retrieval-recall metric** added to the eval (does the expected-table set actually get retrieved for each question?). This pairs naturally with §3c (the eval-score CI gate) and makes retrieval regressions visible.
- No regression on queries that already work; offline suite green.

## Files likely touched

- `assistant/sql_assistant.py` (`_retrieve` and helpers; possibly a new schema-linking step)
- NEW `assistant/schema_graph.py` (FK-edge extraction — reuse `validate.build_catalog`'s parsing)
- `ingest/build_index.py` (only if changing chunking/indexing granularity for column-level retrieval)
- `eval/run_eval.py` + `eval/test_questions.yaml` (retrieval-recall metric; ensure the gains/losses case's expected tables include `members`)
- `docs/OPEN_WEBUI_SETUP.md` (parity note only if retrieval behavior changes)

## How to start next session

1. Read this doc + `docs/specs/2026-06-08-openwebui-local-api-design.md`.
2. **Reproduce the miss first:** run the gains/losses query through the API/GUI and confirm `members.md` isn't retrieved (inspect the result's citations, or temporarily log the retrieved chunk filenames in `_retrieve`). This is your before/after anchor.
3. `superpowers:brainstorming` over approaches 1–5 → pick. Then `writing-plans` → `subagent-driven-development` (same flow that delivered §3a — it worked well).

## Roadmap context

- ✅ This-week hardening (PRs #3/#5/#6/#7), §2d validator wiring (#8), §3a GUI unification (merged to `main`).
- ⬜ **§3b schema-linking retrieval — THIS doc.**
- ⬜ §3c eval-score CI gate (needs a self-hosted Ollama runner) — pairs with the retrieval-recall metric above.
- ⬜ §4 certified query bank → Cube semantic layer (for SQL Server; not dbt MetricFlow).
