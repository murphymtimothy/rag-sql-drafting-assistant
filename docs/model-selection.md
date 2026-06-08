# Model Selection — Local LLM Bake-off

**Date:** 2026-06-08
**Decision:** the default generation model is **`qwen2.5-coder:7b`**.
**Constraints:** fully local (Ollama, no cloud — this is a credit-union data tool), single workstation with **~16 GB GPU VRAM**.

---

## TL;DR

Five local models were evaluated on the project's own eval harness (15 curated questions, RAG-on, scored by the hardened `eval/checker.py`), five trials each. `qwen2.5-coder:7b` was chosen: it ties the field's best on grounding, is the **only model with perfect refusal safety**, is the **fastest**, the **most consistent**, and has the **smallest footprint** (leaving the most VRAM headroom for context). A sixth model — Gemma 4 (`gemma4:26b-a4b-it-qat`, released later) — was assessed separately on the single hardest query: it is the strongest *reasoner* of the field but impractical on 16 GB (see the **Gemma 4 addendum** below).

| Model | overall ±std | spread | real (12 Q) | trick decline | latency |
|---|---|---|---|---|---|
| **qwen2.5-coder:7b** ✅ | **0.893** ± 0.033 | 0.83–0.93 | 0.867 | **15/15** | **1.7 s** |
| qwen2.5-coder:14b | 0.900 ± 0.037 | 0.87–0.97 | **0.908** | 13/15 | 3.2 s |
| codegemma:7b | 0.787 ± 0.062 | 0.67–0.83 | 0.900 | **5/15** ⚠️ | 2.0 s |
| gemma3:12b | 0.760 ± 0.053 | 0.67–0.80 | 0.733 | 13/15 | 3.2 s |
| gpt-oss:20b | 0.747 ± **0.154** | 0.50–0.97 | 0.733 | 12/15 | 2.2 s |

- **overall** = mean of the per-trial mean scores across 5 trials; **±std** = population stddev of those trial means.
- **real** = mean over the 12 non-trick questions. **trick decline** = correct refusals out of 3 trick questions × 5 trials = 15.
- **latency** = mean per-generation wall-clock over all 75 generations (model warm).

---

## Methodology

- **Harness:** `eval/run_eval.py` logic, RAG-on only (the model-comparison axis), 5 independent trials per model, identical prompts and retrieval (`nomic-embed-text`, top-k 5).
- **Scoring:** the **hardened** `eval/checker.py` (see below). It measures **table grounding** (all expected tables referenced, no hallucinated tables) and **refusal accuracy** on the 3 trick questions. It does **not** execute SQL or check dialect/window-function correctness — that axis is covered by manual review (see `docs/PROJECT_OVERVIEW.md` §7).
- **No-RAG baseline** (for the chosen model, separate run): **0.30** vs **0.89** RAG — retrieval remains the dominant factor regardless of model.

---

## Per-model findings

- **`qwen2.5-coder:7b` (chosen).** Grounding statistically tied with the 14b (0.893 vs 0.900, well inside the std), **perfect refusal (15/15)**, fastest (1.7 s), tightest variance (±0.033), ~4.7 GB so the most VRAM headroom for a large context window. A non-reasoning code model — no reasoning-overflow failure mode.
- **`qwen2.5-coder:14b`.** Best on real SQL-writing questions (0.908), but missed 2 refusals (13/15) and is 2× slower. A reasonable alternative if complex-query correctness matters more than the marginal speed/safety.
- **`codegemma:7b` — cautionary.** *Elite* on real questions (0.900, tied for best) but **catastrophic on refusals (5/15)** — it invents SQL for out-of-scope questions two-thirds of the time. This is exactly the dangerous "confident hallucination" failure the project exists to prevent; disqualifying as a default despite the strong real-query score. It is also an older model (Gemma 1 base, 2024).
- **`gemma3:12b`.** A modern *generalist*; the generalist tax shows — 0.733 on real questions, below the code specialists, while being slower. Decent refusal (13/15).
- **`gpt-oss:20b` — incumbent, retired.** Lowest overall (0.747) **and** by far the least consistent (±0.154, runs ranging 0.50–0.97). As a reasoning model at this VRAM it must run at low reasoning effort (see below), and its quality/latency swing wildly run-to-run. Not suitable as a dependable default.

---

## Models considered but not viable on 16 GB / on-prem

- **Gemini / Claude / GPT (cloud):** ruled out by data residency — credit-union schema and query results must not leave the network.
- **`qwen3-coder` (code-specialized Qwen3):** smallest variant is 30B-A3B (~19 GB) → does not fit 16 GB cleanly; 480B is cloud-scale. The general `qwen3:8b`/`14b` *fit* but are non-specialized hybrid-reasoning models that reintroduce the reasoning-overflow wrinkle.
- **`qwen3:32b`, `qwen3:30b` MoE, `gemma3:27b`, `qwen2.5-coder:32b`:** ~17–20 GB → over budget (CPU offload only → slow).
- **`gemma4:26b-a4b-it-qat` (Gemma 4 QAT):** *fits* 16 GB on paper (~16 GB weights) but runs in CPU offload (~40 s) and must have thinking disabled to produce output at all — yet it wrote the **best SQL of any model tested**. Impractical here; see the addendum.

---

## Operational note: reasoning models and the context window

`gpt-oss` is a **reasoning model**: it emits a hidden reasoning channel before the final answer. At Ollama's default `num_ctx` of **4096**, that reasoning can consume the entire window and the final `content` comes back **empty** (`finish_reason=length`). Raising `num_ctx` is not viable here:

- Ollama's **OpenAI-compatible endpoint silently ignores** an `options.num_ctx` override.
- The **native** endpoint honors it, but reloading the 13.8 GB model at 8k+ context **exceeds 16 GB VRAM and crashes** (`CUDA error`).

The fix in `assistant/sql_assistant.py` is to run reasoning-style models at **`reasoning_effort="low"`** (guarded to `gpt-oss`), which keeps the full answer inside 4096. **The chosen `qwen2.5-coder:7b` is not a reasoning model and is unaffected** — this is one more reason the coder model is the better operational fit.

---

## Addendum: Gemma 4 (`gemma4:26b-a4b-it-qat`) — best reasoner, impractical at 16 GB

Gemma 4 (released after the initial bake-off) is a 26B Mixture-of-Experts model (4B active) whose QAT 4-bit build is advertised to fit 16 GB. It was assessed on the single hardest question — *"list every member who owns ≥1 credit-card account, with their most recent reward-point balance and month-over-month change"* — by manual review, not the full 15-question harness.

**Quality — the best of any model tested.** When allowed to finish, it:

- applied the `card_rewards.md` rule exactly — `ROW_NUMBER() … ORDER BY transaction_date DESC, reward_id DESC` (including the `reward_id` tiebreak that *both* Qwen models dropped), and **explicitly refused to use `MAX`/`SUM` on `points_balance`, citing the naming convention**;
- wrote correct T-SQL (`DATEFROMPARTS`/`DATEADD`/`EOMONTH`), correct per-card→per-member aggregation, and correct card-holder filtering.

It reasons about the ledger semantics better than anything else in the field — the quality ceiling.

**Two practical blockers on 16 GB:**

1. **Empty output by default (reasoning overflow).** Like `gpt-oss`, Gemma 4 is a reasoning model; its hidden reasoning (~2,036 tokens) fills the 4096 window before the answer (`finish_reason=length`). The `gpt-oss` fix does **not** transfer: `reasoning_effort="low"` is **silently ignored** for Gemma 4 on Ollama's OpenAI-compatible endpoint. The only things that worked were **`think: false`** on Ollama's **native** `/api/chat` (which `sql_assistant.py` does not use), or, in Open WebUI, the **`think (Ollama)` toggle Off on the base model**.
2. **~40 s latency.** ~16 GB of weights on a 16 GB GPU → CPU offload, ~20–40× slower than `qwen2.5-coder:7b`. Raising `num_ctx` to give reasoning room only deepens the VRAM crunch.

**Run-to-run variance.** Even with thinking off it is non-deterministic: one run produced a clean, correct query (`TOP 1 … WHERE transaction_date <= EOMONTH(GETDATE())`); another produced one with a `DATEFROMPARTS(YEAR(DATEADD(...), 1), …)` paren slip (two args to `YEAR()` → compile error) plus a "current calendar month" vs. "most recent" flaw. Reinforces *it drafts; a human validates*.

**Open WebUI config that works** (Admin → Settings → Models, on the **base** model):

- `think (Ollama)`: **Off** — the empty-output fix. Set it on the *base* model; the toggle is unreliable on *custom* Workspace models ([open-webui #14975](https://github.com/open-webui/open-webui/issues/14975)).
- `num_ctx`: 4096 is sufficient once thinking is off.
- System prompt: the same T-SQL grounding prompt; attach the `schema_docs` knowledge base for RAG (citations confirm retrieval works).

**Verdict.** Best reasoner, but not practical on this hardware: empty without pipeline rewiring, slow when working. Revisit on a **≥24 GB GPU** (where it runs on-device at speed) with the assistant wired to call Ollama's native `think: false` path.

---

## Checker hardening (so the scores are trustworthy)

The first, single-run sweep was scored by an earlier checker that mis-scored valid SQL. `eval/checker.py` was hardened (with regression tests in `tests/test_checker.py`) to:

- strip schema qualifiers (`dbo.`) and T-SQL bracket-quoting so `dbo.members` isn't read as a table named `dbo`;
- ignore **CTE names** (`WITH x AS …`) and **derived-table aliases** (`) x`) so they aren't flagged as hallucinated tables;
- credit **prose answers** to "which table…?" / "what columns…?" lookups when no SQL is produced;
- recognize a broader set of real refusal phrasings ("does not include", "no mention of", "I apologize", …).

After hardening, every model's score rose and the rankings stabilized — the table above is the post-hardening, 5-trial result.

---

## Reproduce

```powershell
ollama pull qwen2.5-coder:7b   # default; others: qwen2.5-coder:14b, gemma3:12b, codegemma:7b, gpt-oss:20b
python ingest/build_index.py
python eval/run_eval.py         # single RAG-on/off run for the default model → logs/eval_report.md
```

The 5-trial multi-model sweep was a throwaway driver over `answer_question` + `check_answer`; the per-run reports live in `logs/eval_report_*.md` (gitignored).
