# Open WebUI Setup — the team front end

Open WebUI is the **off-the-shelf GUI** for this assistant. We do **not** build or maintain a
custom front end. Open WebUI is multi-user, self-hostable on-prem via Docker, supports
persistent knowledge bases, and lets you import/configure models and the system prompt from
the UI. This document is the exact, reproducible configuration so a teammate can stand it up
from scratch and get the **same grounded T-SQL behavior** the scripted pipeline produces.

> **Why this matters.** The Open WebUI retrieval settings below (chunking, Top-K, hybrid
> search, reranker) are deliberately aligned to the scripted pipeline so the eval harness is a
> faithful proxy for what the GUI does. At ~20 mock tables this barely matters; at Redwood's
> hundreds of tables, retrieval tuning is the whole ballgame. See `docs/PORTING_TO_ONPREM.md`.

---

## 0. Prerequisites

- Ollama running locally with the models pulled:
  ```
  ollama pull qwen2.5-coder:14b
  ollama pull bge-m3
  ```
  (The reranker `bge-reranker-v2-m3` is downloaded by Open WebUI itself the first time you set
  it — it is not an Ollama model.)
- Open WebUI running and pointed at your Ollama instance. The standard local Docker run:
  ```
  docker run -d -p 3000:8080 \
    --add-host=host.docker.internal:host-gateway \
    -v open-webui:/app/backend/data \
    --name open-webui --restart always \
    ghcr.io/open-webui/open-webui:main
  ```
  Then open http://localhost:3000 and create the first (admin) account. If Ollama isn't
  auto-detected, set the Ollama base URL under **Admin Panel → Settings → Connections** to
  `http://host.docker.internal:11434`.

---

## 1. Document / RAG settings — Admin Panel → Settings → Documents

Set these exactly:

| Setting | Value |
|---|---|
| Embedding Model Engine | **Ollama** |
| Embedding Model | **`bge-m3`** |
| Text splitter | **Token** |
| Chunk Size | **large enough that a typical table doc stays in ONE chunk** (e.g. `2000`+; see note) |
| Chunk Overlap | `0` |
| Markdown-header splitting | **OFF** (do not split a table's documentation across chunks) |
| Top K | **5** |
| Hybrid Search | **ON** |
| Reranking Model | **`bge-reranker-v2-m3`** |

**Chunk-size note.** The goal is **one chunk per table doc**. Pick a chunk size larger than
your biggest table doc so it is never split on its headers. The mock docs are small; a real
table with hundreds of columns is bigger, so size up accordingly (bge-m3 accepts up to 8192
tokens). This mirrors `ingest/build_index.py`, which loads each `.md` as a single flat
document with `CHUNK_SIZE = 8192`, `CHUNK_OVERLAP = 0`, and no markdown-header splitting.

After changing embedding settings you must **re-index** existing knowledge (re-upload the docs,
step 2) — changing the embedder invalidates prior embeddings.

### RAG Template — Admin Panel → Settings → Documents → RAG Template

**Replace the default template.** This is the eighth parity lever and the easiest one to miss:
Open WebUI ships a default RAG template that wraps `{{CONTEXT}}` with its own behavioral
instructions — including *"If the answer isn't present in the context but you possess the
knowledge … provide the answer using your own understanding."* That line **licenses the model
to invent a schema from training data** when retrieval is thin, directly contradicting the
system prompt's grounding rules and producing hallucinated table/column names (the failure mode
the scripted pipeline does not have, because it never uses this template). Paste this neutral,
grounding-consistent template in its place — it strips the hallucination fallback while keeping
the `[id]` citation mechanism Open WebUI uses for source attribution:

```
### Task
Draft a Microsoft SQL Server (T-SQL) query that answers the user's question using ONLY the schema documentation in the sources below. Follow every rule in your system prompt — grounding, T-SQL dialect, the correctness patterns, and the output format.

### Source rules
- The sources below are the complete, authoritative schema. Use only the tables and columns that appear in them.
- If the sources do not contain a table or column needed to answer, do NOT invent one and do NOT fall back on general or outside knowledge. Say plainly what is missing and name the schema doc(s) you would need.
- If the sources are unreadable or empty, say so rather than guessing.
- When you use information from a source whose <source> tag has an id attribute (e.g. <source id="1">), add an inline citation like [1] next to it. Do not cite sources without an id attribute. Do not use XML tags in your response.
- Respond in the same language as the user's question.

<context>
{{CONTEXT}}
</context>
```

The template defers all behavior to the system prompt (step 3), which is the single source of
truth. Keeping it neutral is what makes the scripted path and the GUI prompt equivalently —
without this, the two paths disagree on the most important rule.

---

## 2. Create the knowledge base — Workspace → Knowledge → + Create Knowledge Base

1. Name it exactly **`Schema Docs`**.
2. Upload **all** files from `schema_docs/*.md`.
3. Whenever the schema docs change (e.g. after re-running
   `extraction/extract_schema_from_sqlserver.py`), **re-upload / reindex** the knowledge base so
   embeddings stay current. The scripted side has `refresh/refresh_scheduler.py` for this; in
   Open WebUI it is a manual re-upload.

> **Retrieval mode must be Focused Retrieval, not Full Context.** A knowledge base attached to a
> model can run in two modes: **Focused Retrieval (RAG)** — Top-K + hybrid search + reranker,
> injecting only the ~5 relevant chunks — or **Full Context**, which injects *every* document
> verbatim and **silently ignores Top-K, Hybrid Search, and the reranker entirely**. With 20
> table docs, Full Context dumps all 20 (~9–10K tokens), overruns the context window, and the
> model truncates to a word or two before stopping. **Toggle the mode by clicking the attached
> `Schema Docs` chip in the chat** (or on the knowledge item in the model editor) and make sure
> it reads **Focused Retrieval**. A correct query for this collection should cite ~5 sources, not
> 20. This single setting overrides every retrieval lever in §1 — get it wrong and none of them
> apply.

---

## 3. Create the model — Workspace → Models → + Add Model

1. **Base model:** `qwen2.5-coder:14b`.
2. **System prompt:** paste the T-SQL grounding prompt **verbatim** (identical to
   `SYSTEM_PROMPT` in `assistant/sql_assistant.py`):

   ````
   You are a SQL-drafting assistant for analysts at a credit union. You draft Microsoft SQL Server (T-SQL) SELECT queries for a human analyst to review and run. You never execute SQL and you never modify data.

   # Grounding — your most important rule
   - The Schema Context provided with each question is the complete and authoritative schema. Use ONLY tables and columns that appear there.
   - Never invent, assume, or recall a table or column name from memory — not even names that are "standard" for banking or credit-union data. If you are about to write a name that does not appear in the Schema Context, stop: that is a hallucination, not an answer.
   - If the Schema Context lacks a table or column needed to answer, do not write SQL that uses it. Instead say plainly what is missing and name the specific table doc(s) you would need. A correct "I can't answer that from the provided schema" is a success, not a failure.
   - Before you finalize, re-read your query and confirm that every table, every column, and every alias you reference is defined — columns in the Schema Context, aliases in your own query.

   # Dialect — Microsoft SQL Server (T-SQL) only
   - Use: TOP (not LIMIT); GETDATE() / SYSDATETIME() (not NOW()); EOMONTH(), DATEADD(), DATEDIFF(); ISNULL() / COALESCE(); OFFSET ... FETCH for paging; [bracket] quoting; window functions (ROW_NUMBER, LAG, LEAD, SUM() OVER ()).
   - Never use MySQL- or Postgres-only syntax: no LIMIT, no backticks, no NOW(), no ILIKE, no :: casts.
   - Draft read-only SELECT queries unless explicitly asked otherwise. Never emit INSERT / UPDATE / DELETE / DDL by default.

   # Correctness patterns — apply when the question calls for them
   These analytic shapes are easy to get subtly wrong. When relevant, follow them; do not force them onto simple queries.
   - Most-recent / current value per entity: select the latest row with ROW_NUMBER() OVER (PARTITION BY <entity_key> ORDER BY <date> DESC, <pk> DESC) and keep where it equals 1. Always include the primary key as a tiebreaker so same-date ties don't return duplicates.
   - Running-balance / ledger columns (a column that already carries a cumulative total on each row, e.g. a points or account balance): read it from the latest qualifying row using the pattern above. Never aggregate it with MAX(), SUM(), or AVG() — the running total already includes prior rows, so SUM multiplies it and MAX returns the high-water mark, not the closing balance.
   - Period-over-period change (month-over-month, etc.): (1) reduce to one value per entity per period first — typically the period's closing value via the latest-row pattern within each period; (2) then apply LAG(value) OVER (PARTITION BY <entity> ORDER BY <period>) to fetch the prior period; (3) subtract current - prior. Do not collapse to a single latest row before the LAG, or there is no prior period left to compare against. Skeleton (substitute real names from the Schema Context):
       WITH per_period AS (
           SELECT <entity>, EOMONTH(<date>) AS period_end, <value>,
                  ROW_NUMBER() OVER (PARTITION BY <entity>, EOMONTH(<date>)
                                     ORDER BY <date> DESC, <pk> DESC) AS rn
           FROM <ledger_table>
       )
       SELECT <entity>, period_end, <value>,
              <value> - LAG(<value>) OVER (PARTITION BY <entity> ORDER BY period_end) AS mom_change
       FROM per_period
       WHERE rn = 1;
   - One-to-many joins: when a join fans out (one parent -> many children), aggregate or filter the child side to the intended grain before joining so rows aren't double-counted.

   # Output
   - Give the T-SQL in a single ```sql code block, then 2-3 sentences explaining the join path and any assumptions.
   - If you declined because of a schema gap, give no SQL — just the explanation of what's missing.
   - End by naming the schema doc(s) you used as citations.
   ````

3. **Knowledge:** attach the **`Schema Docs`** knowledge base to this model.
4. **Advanced Params → Context Length (num_ctx):** **≥ 8192**. This is **per-model** and
   **not inherited** — Open WebUI / Ollama default many local models to **2048 tokens**, which is
   smaller than this assistant's system prompt + 5 retrieved table docs. If `num_ctx` is left at
   the default, the input alone overruns the window and the model emits **one or two words then
   stops** (the truncation looks like a broken answer, not an error). Set it explicitly here and
   re-check it after any model edit.
5. Save.

**Thinking/reasoning toggle.** `qwen2.5-coder` is a non-thinking coder model, so the
empty-output ("no output") bug does not apply. If anyone ever loads a *reasoning* base model,
set the **`think (Ollama)` toggle Off on the base model** — it is unreliable when set on a
custom Workspace model.

---

## 4. Usage

In a chat with the model created above, scope retrieval to the schema docs by typing:

```
#Schema Docs
```

then ask your question, e.g. *"Write a query showing each member's active loans and their
current delinquency status."* The answer should be **grounded T-SQL with citations** to the
correct table docs (e.g. `members.md`, `loans.md`, `loan_status_history.md`).

---

## 5. Parity with the scripted pipeline

| Lever | Scripted pipeline | Open WebUI |
|---|---|---|
| LLM | `qwen2.5-coder:14b` (`DEFAULT_MODEL`) | base model `qwen2.5-coder:14b` |
| Embedder | `bge-m3` (`EMBED_MODEL`) | Embedding Model `bge-m3` |
| Chunking | one flat doc per `.md`, `CHUNK_SIZE=8192`, overlap 0, no header split | Token splitter, large chunk, overlap 0, header-split OFF |
| Top-K | `DEFAULT_K = 5` | Top K = 5 |
| Hybrid | dense (Chroma) + BM25 sparse, RRF-fused | Hybrid Search ON |
| Reranker | `BAAI/bge-reranker-v2-m3` cross-encoder | Reranking Model `bge-reranker-v2-m3` |
| System prompt | `SYSTEM_PROMPT` (Section 5.1 verbatim) | pasted verbatim (step 3) |
| Context wrapper | hand-built `## Schema Context` block (`answer_question`), no behavioral instructions | neutral RAG Template, hallucination fallback removed (§1) |

Because both paths use the same model, embedder, chunking, Top-K, hybrid+rerank, prompt, and a
behaviorally-neutral context wrapper, the on-demand eval (`python eval/run_eval.py`) is a
credible proxy for the GUI's behavior. The last row matters most: the scripted path never wraps
context in a template, so if Open WebUI keeps its *default* RAG template the two paths diverge
on grounding — the GUI's template would invite the hallucination the system prompt forbids.

---

## 6. Troubleshooting — when the GUI misbehaves but the scripted path is fine

These are Open WebUI-specific foot-guns. None of them show as errors — they silently degrade the
answer, so they're easy to lose hours to. The scripted pipeline (`assistant/sql_assistant.py`)
is unaffected by all of them; if the script grounds correctly and the GUI doesn't, the cause is
almost always one of these.

| Symptom | Likely cause | Fix |
|---|---|---|
| Answer is **one or two words then stops** (e.g. just `To`) | Context window overflow. Either `num_ctx` is at the 2048 default (§3 step 4), or the knowledge base is in **Full Context mode** dumping all docs (next row). | Set `num_ctx` ≥ 8192; switch to Focused Retrieval. |
| Response cites **~20 sources** (all tables) instead of ~5 | Knowledge base is in **Full Context mode** — it injects every doc verbatim and **ignores Top-K, Hybrid Search, and the reranker**. | Click the attached `Schema Docs` chip → set **Focused Retrieval** (§2). |
| SQL uses **invented table/column names** (e.g. `Members`, `CreditCardAccounts`) | The **default RAG Template** licenses answering from model knowledge when context is thin. | Replace it with the neutral template in §1. |
| Per-model settings (num_ctx, etc.) **don't take effect** | A global **`Function Calling: native`** setting (Admin Panel → Settings → Models → ⚙️ → Model Parameters) silently overrides per-model Advanced Params. | Set Function Calling to **Default**, or override it explicitly in the model's Advanced Params. |
| Retrieval **returns nothing / wrong docs** after changing the embedder | Changing the **Embedding Model** invalidates all prior embeddings; retrieval fails silently against the old vectors. | Re-upload / reindex the `Schema Docs` knowledge base (§2 step 3). |
| Grounding **degrades over a long multi-turn chat** | RAG context injected into the *user* message shifts position each turn, invalidating the KV cache and re-processing. | Optional: set env `RAG_SYSTEM_CONTEXT=True` to pin context to the system message; or start a fresh chat. |

**Fast triage:** if the GUI looks wrong, first run the same question through the scripted path
(`python -c "from assistant.sql_assistant import answer_question; print(answer_question('<q>')['sql'])"`).
If the script is correct, the bug is GUI config — walk this table. If the script is *also* wrong,
it's a prompt/retrieval issue in the shared core, and the eval harness is the place to debug it.
