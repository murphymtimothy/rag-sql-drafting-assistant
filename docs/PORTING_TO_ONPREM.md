# Porting home → on-prem

This home build on a personal PC is a **rehearsal** for an on-prem proof-of-concept at the credit union
Credit Union: on-prem, Microsoft SQL Server (T-SQL), hundreds of tables — some with hundreds of
columns and millions of rows — shown to a small team of analysts/engineers and leadership to
demonstrate what a **local LLM in a regulated enterprise environment** can do. These notes
capture what changes, what doesn't, and the few things to keep architecturally open.

## The big one: millions of rows are irrelevant to the RAG

We never embed row data — **only schema docs**. What scales is *schema breadth* (hundreds of
tables × hundreds of columns ≈ a few thousand schema chunks), which is a **modest retrieval
corpus**. The millions of rows live in the warehouse and are only ever touched by the human who
reviews and runs the drafted SELECT — never by the assistant, never by the index.

Concretely: one chunk per table doc means the index size scales with **table count**, not data
volume. A few thousand chunks is comfortable for Chroma and for Open WebUI's built-in RAG.

## The real enterprise difficulty: disambiguation

At 20 mock tables, retrieval is nearly trivial. At production scale the hard problem is
**disambiguation** — many similar tables/columns and many plausible join paths. Two levers solve
this, and both are things to invest in deliberately:

1. **The reranker.** `bge-reranker-v2-m3` re-scores the fused dense+sparse candidates by actual
   query relevance, which is what separates the right table from five plausible look-alikes.
   This is mostly inert at 20 docs but becomes load-bearing at scale — which is exactly why it
   is wired into both the scripted pipeline and Open WebUI now, as rehearsal.
2. **Well-written FK / relationship sections in each table doc.** The model can only join
   correctly if the docs spell out the foreign keys and relationships. At scale this doc quality
   is the single highest-leverage investment. The `## Foreign keys / relationships` section in
   each schema doc is not decoration — it is the join-path knowledge the model retrieves.

## The bridge: `extraction/extract_schema_from_sqlserver.py`

This is the seam between the mock home build and the real warehouse. At work it **regenerates
`schema_docs/` from the real catalog**:

```powershell
$env:SQL_SERVER_DSN = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=...;DATABASE=...;UID=readonly_user;PWD=..."
$env:SQL_SERVER_SCHEMA = "dbo"   # optional, defaults to dbo
python extraction/extract_schema_from_sqlserver.py
python ingest/build_index.py
```

It is, and must remain, **read-only and metadata-only**:

- It issues only `SELECT` against system catalog/INFORMATION_SCHEMA views
  (`INFORMATION_SCHEMA.TABLES/COLUMNS`, `sys.foreign_keys`, `sys.extended_properties`, etc.).
- It never reads table **data**, and never writes/alters anything.
- Required grants are read-only: `SELECT` on the catalog views + `VIEW DEFINITION`.
- Columns/tables without `MS_Description` extended properties emit a
  `<!-- TODO: no description on file -->` placeholder — grep for it to build a documentation
  punch list. **Filling those TODOs (especially the FK/relationship notes) is the doc-quality
  work that makes disambiguation succeed.**

Keep this script clean and central; it is the thing that makes "swap mock → real" a two-command
operation.

## Scaling paths to keep open (build NOTHING now)

These need nothing at home but should remain architecturally possible so the team's experience
never has to change:

- **If Open WebUI's built-in RAG hits a ceiling** (retrieval quality plateaus at scale), plug a
  custom retrieval backend behind it via **Open WebUI Pipelines/Functions**. The scripted
  pipeline in this repo is the reference implementation of that backend — the team's UI never
  changes; only what answers the retrieval call does.
- **If ~5 concurrent users strain Ollama**, swap **vLLM** behind the same OpenAI-compatible
  front end. Open WebUI and the scripted client both speak the OpenAI API, so the inference
  engine is replaceable without touching the GUI or the eval.

Do **not** build either of these now. They are noted only so today's choices don't foreclose
them. (Per the guardrails: no vLLM / heavyweight serving at home.)

## What stays exactly the same

- Fully local / offline; no cloud, no data leaving the machine.
- T-SQL as the only target dialect.
- Open WebUI as the off-the-shelf GUI (no custom front end).
- Grounding via retrieval, never fine-tuning — schema stays in plain files we control.
- The eval harness as the evidence layer: `python eval/run_eval.py` regenerates
  `logs/eval_report.md` (RAG-on vs RAG-off) against whatever `schema_docs/` currently holds.
