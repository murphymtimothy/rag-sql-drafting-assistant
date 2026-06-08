# Design: Local OpenAI-compatible API so Open WebUI uses the validated pipeline

**Date:** 2026-06-08
**Status:** Draft for review
**Roadmap item:** §3a — unify the Open WebUI path with the scripted path (single source of truth)

## Context & problem

The assistant has two front ends that are supposed to behave identically:

- **Scripted/eval path** — `assistant/sql_assistant.py:answer_question()` does retrieval → `SYSTEM_PROMPT` → Ollama generation → (as of PR #8) the deterministic `validate_sql()` gate.
- **Open WebUI (GUI)** — a separate Docker container that runs *its own* retrieval and prompting against Ollama. It **never calls our Python**, so it gets **none** of the validation gate and can drift from the scripted path on retrieval/prompt settings (the divergence documented in `OPEN_WEBUI_SETUP.md`).

The two paths are kept in sync today only by hand-copying ~8 settings into the OWUI admin UI. The validator (the thing that stops hallucinated columns from shipping) does not run in the GUI at all.

**Goal:** make Open WebUI a thin client of `answer_question()` so the GUI gets the *exact* retrieval + prompt + validation as the scripted path — one source of truth, no hand-synced settings, hallucinated SQL gated in the GUI too.

### Deployment reality (verified in repo, drives several decisions)

- **Ollama runs natively on the host** (`localhost:11434`), not in a container: the scripted path uses `http://localhost:11434/v1` (`sql_assistant.py:125`); Open WebUI reaches it via `http://host.docker.internal:11434` with `--add-host=host.docker.internal:host-gateway` (`OPEN_WEBUI_SETUP.md:25-35`).
- **No compose stack / no Dockerfile exists.** Open WebUI is the only container, launched standalone. Host is Windows 11; Ollama uses the host GPU.
- The cross-encoder reranker (`bge-reranker-v2-m3`) runs **in-process** and wants the GPU; GPU-in-container on Windows Docker Desktop is impractical and CPU reranking does not scale to Redwood's hundreds of tables.

## Decisions (settled with the user)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Response streaming | **Non-streaming generation.** Generate fully, then return. (But still speak the SSE wire protocol — see API contract.) |
| 2 | Conversation context | **Multi-turn aware.** Thread recent history into the prompt so follow-ups build on the prior draft. |
| 3 | Integration protocol | **OpenAI-compatible endpoint** (`/v1/chat/completions` + `/v1/models`). OWUI connects to it natively as a "model"; zero custom OWUI code. |
| 4 | Runtime | **Native host process** (`uvicorn`), not a container. Reuses the host GPU for the reranker (parity + scales), talks to Ollama at `localhost:11434` unchanged, OWUI reaches it via `host.docker.internal:8000`. |
| 5 | Auth | **Static bearer token**, fail-closed (service refuses to start if the token env var is unset). |

## Goals / non-goals

**Goals:** GUI uses `answer_question()` verbatim; validation verdict visible in the GUI; multi-turn refinement; no hand-synced retrieval settings; secured by a token; fully testable offline.

**Non-goals (this iteration):** token-by-token streaming UX; containerization/compose (revisit if Redwood mandates it); replacing Ollama; auth beyond a shared token (no per-user identity); rate limiting.

## Architecture

A new **`serve/`** package — a thin protocol adapter. **All SQL logic stays in `answer_question()`**; `serve/` only translates OpenAI protocol ↔ pipeline.

```
Open WebUI (container) ──POST /v1/chat/completions (Bearer)──▶ serve/app.py (host:8000)
                                                                │ map OpenAI messages → (question, history)
                                                                │ short-circuit OWUI task prompts (titles/tags)
                                                                ▼
                                          answer_question(question, history=…, rag_enabled=True)
                                          (retrieval → SYSTEM_PROMPT → Ollama@localhost:11434 → validate_sql)
                                                                │ content = explanation + validation verdict
                                                                ▼
                                          OpenAI ChatCompletion (JSON or SSE) ──▶ rendered in GUI
```

### Files

| File | Purpose |
|------|---------|
| `serve/__init__.py` | package marker |
| `serve/config.py` | env config: `SQL_API_TOKEN` (required), `SQL_API_HOST`/`SQL_API_PORT`, model id, history cap |
| `serve/schemas.py` | Pydantic models for the OpenAI request/response/chunk + model-list shapes |
| `serve/auth.py` | FastAPI dependency: bearer check via `secrets.compare_digest` (timing-safe) |
| `serve/conversation.py` | map OpenAI `messages[]` → `(question, history)`; detect/short-circuit OWUI task prompts |
| `serve/app.py` | FastAPI app + routes |
| `serve/__main__.py` | `python -m serve` → launches uvicorn |
| `tests/test_serve.py` | offline tests (FastAPI `TestClient`, `answer_question` mocked) |

New deps in `requirements.txt`: `fastapi`, `uvicorn[standard]`, `httpx` (TestClient).

## API contract

- **`GET /v1/models`** → one entry, id `cu-sql-assistant`, so it shows in the OWUI model dropdown.
- **`POST /v1/chat/completions`** → standard OpenAI request.
  - We **own the system prompt** (`SYSTEM_PROMPT`), so any incoming `system` message from OWUI is ignored.
  - `question` = content of the **last `user` message**; `history` = prior user/assistant turns (trimmed — see Multi-turn).
  - `model` field: if present and not `cu-sql-assistant`, return **404** (unknown model); otherwise ignored (always our pipeline).
  - Response content = the model's explanation (including its ```sql block) with the **validation verdict appended** when `validate_sql` is not ok:
    ```
    ---
    > ⚠️ Automated validation flagged this draft — review before running:
    > - Column binding failed: Unknown column: member_id
    > - Invalid status_cd value 'INACTIVE' …
    ```
  - Returns a stub `usage` object (token counts not computed this iteration).
- **`GET /health`** → liveness for monitoring.

### Streaming wire protocol (nuance behind decision #1)

OWUI sends `stream: true` by default. "Non-streaming" refers to *generation* — we still must speak SSE:

- `stream: true` → emit an **early role chunk** (`{"delta":{"role":"assistant"}}`) immediately to hold the connection, run blocking generation, then send the full content as a single content chunk, then `data: [DONE]`.
- `stream: false` → return one plain `ChatCompletion` JSON body.

Generation stays blocking either way; we only satisfy the requested envelope.

## Multi-turn handling (decision #2, with self-review correction)

`answer_question()` gains an **optional** `history: list[dict] | None = None` (default `None` → CLI/eval/tests unchanged).

- **Retrieval key (corrected):** when `history` is present, retrieval keys on the **last ~2 user messages combined**, not just the latest. A follow-up like *"now add their branch"* alone would drop `members`/`accounts` from retrieval; combining recent user turns keeps schema context spanning the evolving query.
- **History trimming:** cap by a token budget (Ollama `num_ctx` is tight — overflow has caused empty-output bugs). Prefer keeping prior **user** asks and the **last assistant SQL block** over full prior explanations.
- **Message assembly:** `[system: SYSTEM_PROMPT] + trimmed_history + [user: schema-context-block + latest question]`.
- Each drafted SQL is validated independently (the gate runs on the latest draft).

## Changes to existing code (additive, backward-compatible)

- `assistant/sql_assistant.py:answer_question()` — add optional `history` param; thread it into message construction; when present, build the retrieval query from recent user turns (above). **No change** to the Ollama base URL (host process reaches `localhost:11434` as today).
- No change to any existing caller's behavior (`history` defaults to `None`).

## Deployment & Open WebUI configuration

- **Run:** `python -m serve` (or `uvicorn "serve.app:create_app" --factory --host 0.0.0.0 --port 8000`) as a host process alongside Ollama. Binds `0.0.0.0` so the OWUI container can reach it via `host.docker.internal:8000`; the bearer token guards that exposure.
- **OWUI connection:** Admin → Settings → Connections → add an **OpenAI API** connection: Base URL `http://host.docker.internal:8000/v1`, API key = `SQL_API_TOKEN`. `cu-sql-assistant` then appears as a model.
- **OWUI task model (self-review correction — important):** OWUI fires side calls to the selected model for **title generation, tag generation, search-query building, and autocomplete**. Left on `cu-sql-assistant`, these send prompts like *"Generate a 3-word title"* into our retrieval+SQL pipeline → nonsense + wasted GPU per message. `OPEN_WEBUI_SETUP.md` must instruct: set the **Task Model to a separate plain Ollama model** and **disable autocomplete**. Belt-and-suspenders: `serve/conversation.py` detects OWUI's recognizable task-prompt templates and short-circuits them with a cheap canned response (no retrieval/validation).
- **Supersedes manual config:** once the GUI points at this endpoint, the hand-configured RAG template / system-prompt / knowledge-base steps in `OPEN_WEBUI_SETUP.md` become obsolete for this model (the endpoint owns retrieval + prompt + gate). The doc gets a new "single-source-of-truth via local API" section; the manual-parity section is marked legacy.

## Auth & error handling

- **Auth:** every `/v1/*` route requires `Authorization: Bearer <SQL_API_TOKEN>`, compared with `secrets.compare_digest`. If `SQL_API_TOKEN` is unset, the app **refuses to start** (no accidental open endpoint).
- **Error policy:**
  - *Protocol errors* → proper HTTP codes in the OpenAI error envelope: missing/bad token `401`, unknown model `404`, malformed body `422`, blank/no user message `400`.
  - *Operational/pipeline errors* → returned as a **200 assistant message** with a clear explanation (GUI-friendly, avoids a jarring red error), and logged at error level: Chroma index missing (`RuntimeError("build_index")`) → "the schema index isn't built; run `build_index.py`"; Ollama unreachable → "the model backend is unreachable."
  - Validator failures already fail open inside `answer_question` (degrade to a warning).

## Concurrency

`answer_question()` is blocking (Ollama call + GPU rerank), so the route runs it in a threadpool; Ollama serializes generation anyway. Adequate for a handful of concurrent analysts. Known limitation: no request queue/rate limit this iteration.

## Testing

`tests/test_serve.py`, fully offline (FastAPI `TestClient`, `answer_question` mocked), covering:

- `401` without/with-wrong token; app refuses to start when `SQL_API_TOKEN` unset.
- `GET /v1/models` shape; `404` on unknown model id.
- `messages[]` → `(question, history)` mapping, including the multi-turn retrieval-key behavior (last user message becomes `question`, prior turns become `history`).
- Validation verdict appended to content when `validate_sql` not ok.
- `stream: true` → SSE with an early role chunk, a content chunk, and a terminating `[DONE]`; `stream: false` → JSON body.
- Error mapping (Chroma-missing → friendly 200 message; auth/malformed → HTTP codes).
- OWUI task-prompt short-circuit (a title-generation prompt does not invoke retrieval/validation).

A live end-to-end check (real Ollama + index) is marked `@pytest.mark.integration` and excluded from the offline gate.

## Risks / open questions

- **Token budget for history** — the exact cap needs tuning against `num_ctx`; start conservative (e.g. last 2 turns, ~prior user asks + last SQL) and adjust.
- **OWUI task-prompt detection** is best-effort (templates can change across OWUI versions); the primary mitigation is configuring a separate Task Model, with detection as backup.
- **Concurrency** is threadpool-only; if many analysts hit it at once, Ollama serialization will queue them (acceptable for now).

## Out of scope / future

Streaming generation UX; containerization (revisit for a Redwood compose+GPU stack); per-user auth; pointing the CLI/eval at the HTTP endpoint; rate limiting.
