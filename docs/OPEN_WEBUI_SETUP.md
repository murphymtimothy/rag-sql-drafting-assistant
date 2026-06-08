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

---

## 2. Create the knowledge base — Workspace → Knowledge → + Create Knowledge Base

1. Name it exactly **`Schema Docs`**.
2. Upload **all** files from `schema_docs/*.md`.
3. Whenever the schema docs change (e.g. after re-running
   `extraction/extract_schema_from_sqlserver.py`), **re-upload / reindex** the knowledge base so
   embeddings stay current. The scripted side has `refresh/refresh_scheduler.py` for this; in
   Open WebUI it is a manual re-upload.

---

## 3. Create the model — Workspace → Models → + Add Model

1. **Base model:** `qwen2.5-coder:14b`.
2. **System prompt:** paste the T-SQL grounding prompt **verbatim** (identical to
   `SYSTEM_PROMPT` in `assistant/sql_assistant.py`):

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

3. **Knowledge:** attach the **`Schema Docs`** knowledge base to this model.
4. **Advanced Params → Context Length (num_ctx):** **≥ 8192**.
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

Because both paths use the same model, embedder, chunking, Top-K, hybrid+rerank, and prompt,
the on-demand eval (`python eval/run_eval.py`) is a credible proxy for the GUI's behavior.
