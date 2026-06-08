# Local OpenAI-compatible API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `answer_question()` as a local OpenAI-compatible HTTP API so Open WebUI uses the exact retrieval + prompt + validation pipeline as the scripted path (single source of truth).

**Architecture:** A thin `serve/` FastAPI package translates the OpenAI `/v1/chat/completions` protocol to/from `answer_question()`. It runs as a native host process (reuses the host GPU for the reranker, talks to Ollama at `localhost:11434` unchanged). Open WebUI connects to it as a model via `host.docker.internal:8000`, guarded by a bearer token.

**Tech Stack:** Python, FastAPI, uvicorn, Pydantic v2; pytest + FastAPI `TestClient` (offline, `answer_question` mocked).

**Spec:** `docs/specs/2026-06-08-openwebui-local-api-design.md`

---

## File structure

| File | Responsibility |
|------|----------------|
| `assistant/sql_assistant.py` (modify) | add optional `history` param + `_retrieval_query` / `_trim_history` helpers |
| `requirements.txt` (modify) | add `fastapi`, `uvicorn[standard]`, `httpx` |
| `serve/__init__.py` (create) | package marker |
| `serve/config.py` (create) | env-driven `Settings`; fail-closed token |
| `serve/schemas.py` (create) | Pydantic OpenAI request/response/model-list shapes |
| `serve/auth.py` (create) | bearer-token FastAPI dependency (timing-safe) |
| `serve/conversation.py` (create) | OpenAI messages → `(question, history)`; OWUI task-prompt detection |
| `serve/app.py` (create) | FastAPI app + routes + response formatting |
| `serve/__main__.py` (create) | `python -m serve` → uvicorn |
| `tests/test_serve.py` (create) | offline endpoint tests |
| `docs/OPEN_WEBUI_SETUP.md` (modify) | new "local API" section + task-model config |

Tasks are ordered so each leaves the suite green. Run all tests with the project venv: `.venv/Scripts/python.exe -m pytest -m "not integration" -q`.

---

## Task 1: Add `history` support to `answer_question`

**Files:**
- Modify: `assistant/sql_assistant.py`
- Test: `tests/test_sql_assistant.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sql_assistant.py`:

```python
def test_retrieval_query_combines_recent_user_messages():
    from assistant.sql_assistant import _retrieval_query
    history = [
        {"role": "user", "content": "show active members"},
        {"role": "assistant", "content": "```sql\nSELECT 1\n```"},
    ]
    q = _retrieval_query("now add their branch", history)
    assert "show active members" in q and "now add their branch" in q


def test_retrieval_query_without_history_is_just_the_question():
    from assistant.sql_assistant import _retrieval_query
    assert _retrieval_query("show members", None) == "show members"


def test_answer_question_threads_history_into_messages(tmp_path):
    mock_ollama = _make_mock_openai([0.1] * 768, "```sql\nSELECT member_id FROM members\n```")
    history = [
        {"role": "user", "content": "show active members"},
        {"role": "assistant", "content": "```sql\nSELECT member_id FROM members\n```"},
    ]
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        answer_question("now add their branch", rag_enabled=False,
                        chroma_path=tmp_path, history=history)
    sent = mock_ollama.chat.completions.create.call_args.kwargs["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[-1]["content"].endswith("now add their branch")


def test_answer_question_history_defaults_unchanged(tmp_path):
    # No history → exactly system + user (existing behavior).
    mock_ollama = _make_mock_openai([0.1] * 768, "```sql\nSELECT 1\n```")
    with patch("assistant.sql_assistant.ollama", mock_ollama):
        answer_question("q", rag_enabled=False, chroma_path=tmp_path)
    sent = mock_ollama.chat.completions.create.call_args.kwargs["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sql_assistant.py -k "history or retrieval_query" -v`
Expected: FAIL (`_retrieval_query` not defined / `answer_question` has no `history` kwarg).

- [ ] **Step 3: Add the helpers**

In `assistant/sql_assistant.py`, after the `DEFAULT_K`/`K_SPARSE` constants block, add:

```python
# Multi-turn: cap threaded history (~3 turns) so prompt + schema context don't overflow
# Ollama's context window (num_ctx), which has caused empty-output truncation before.
HISTORY_MAX_MESSAGES = 6
```

Add these module-level helpers near `_extract_sql`:

```python
def _retrieval_query(question: str, history: list[dict] | None) -> str:
    """Build the retrieval query. With multi-turn history, prepend the most recent prior
    user message so schema context spans the evolving ask — a follow-up like 'now add
    their branch' alone would drop the tables named in the previous turn."""
    if not history:
        return question
    prior_user = [m["content"] for m in history if m.get("role") == "user" and m.get("content")]
    return f"{prior_user[-1]}\n{question}" if prior_user else question


def _trim_history(history: list[dict]) -> list[dict]:
    """Keep only the most recent user/assistant turns (count-capped). System messages are
    dropped — this service owns SYSTEM_PROMPT."""
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    return turns[-HISTORY_MAX_MESSAGES:]
```

- [ ] **Step 4: Thread history through `answer_question`**

Change the signature (add the final param):

```python
def answer_question(
    question: str,
    rag_enabled: bool = True,
    model: str = DEFAULT_MODEL,
    k: int = DEFAULT_K,
    chroma_path: Path = CHROMA_PATH,
    schema_docs_path: Path = SCHEMA_DOCS,
    history: list[dict] | None = None,
) -> dict:
```

Replace the retrieval call so it keys on the combined query:

```python
    if rag_enabled:
        chunks, chunk_files, citations = _retrieve(
            _retrieval_query(question, history), k, chroma_path, schema_docs_path
        )
```

Replace the `messages = [...]` construction with:

```python
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(_trim_history(history))
    messages.append({"role": "user", "content": user_content})
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sql_assistant.py -q`
Expected: PASS (new + all existing).

- [ ] **Step 6: Commit**

```bash
git add assistant/sql_assistant.py tests/test_sql_assistant.py
git commit -m "feat(assistant): add optional multi-turn history to answer_question"
```

---

## Task 2: Dependencies + `serve` config (fail-closed token)

**Files:**
- Modify: `requirements.txt`
- Create: `serve/__init__.py`, `serve/config.py`
- Test: `tests/test_serve.py`

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
# Local OpenAI-compatible API (serve/) so Open WebUI uses the validated pipeline.
fastapi>=0.110
uvicorn[standard]>=0.29
httpx>=0.27
```

Install: `.venv/Scripts/python.exe -m pip install "fastapi>=0.110" "uvicorn[standard]>=0.29" "httpx>=0.27" -q`

- [ ] **Step 2: Write failing test**

Create `tests/test_serve.py`:

```python
import pytest


def test_require_token_raises_when_unset(monkeypatch):
    monkeypatch.delenv("SQL_API_TOKEN", raising=False)
    from serve.config import Settings
    with pytest.raises(RuntimeError, match="SQL_API_TOKEN"):
        Settings().require_token()


def test_require_token_returns_when_set(monkeypatch):
    monkeypatch.setenv("SQL_API_TOKEN", "secret")
    from serve.config import Settings
    assert Settings().require_token() == "secret"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -v`
Expected: FAIL (`No module named 'serve'`).

- [ ] **Step 4: Create the package + config**

Create `serve/__init__.py` (empty file).

Create `serve/config.py`:

```python
"""Environment-driven settings for the local SQL-assistant API."""
import os

DEFAULT_MODEL_ID = "cu-sql-assistant"


class Settings:
    def __init__(self) -> None:
        self.token = os.environ.get("SQL_API_TOKEN")
        self.model_id = os.environ.get("SQL_API_MODEL_ID", DEFAULT_MODEL_ID)
        self.host = os.environ.get("SQL_API_HOST", "0.0.0.0")
        self.port = int(os.environ.get("SQL_API_PORT", "8000"))

    def require_token(self) -> str:
        """Return the API token, or raise if unset (fail-closed: never run open)."""
        if not self.token:
            raise RuntimeError(
                "SQL_API_TOKEN is not set — refusing to start (fail-closed). "
                "Set it and configure the same value on Open WebUI's connection."
            )
        return self.token


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt serve/__init__.py serve/config.py tests/test_serve.py
git commit -m "feat(serve): add FastAPI deps and fail-closed config"
```

---

## Task 3: OpenAI request/response schemas

**Files:**
- Create: `serve/schemas.py`
- Test: `tests/test_serve.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_serve.py`:

```python
def test_request_ignores_extra_fields_and_defaults_stream_false():
    from serve.schemas import ChatCompletionRequest
    req = ChatCompletionRequest.model_validate({
        "model": "cu-sql-assistant",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.7,  # extra OpenAI field OWUI sends — must be ignored
    })
    assert req.stream is False
    assert req.messages[0].content == "hi"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py::test_request_ignores_extra_fields_and_defaults_stream_false -v`
Expected: FAIL (no `serve.schemas`).

- [ ] **Step 3: Create the schemas**

Create `serve/schemas.py`:

```python
"""Minimal OpenAI-compatible request/response shapes (only what Open WebUI uses)."""
from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatCompletionRequest(BaseModel):
    # OWUI sends many extra fields (temperature, top_p, ...) — ignore them.
    model_config = ConfigDict(extra="ignore")
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = False


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage = Field(default_factory=Usage)


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "local"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelCard]
```

- [ ] **Step 4: Run test to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py::test_request_ignores_extra_fields_and_defaults_stream_false -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serve/schemas.py tests/test_serve.py
git commit -m "feat(serve): OpenAI-compatible request/response schemas"
```

---

## Task 4: Conversation mapping + OWUI task-prompt detection

**Files:**
- Create: `serve/conversation.py`
- Test: `tests/test_serve.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_serve.py`:

```python
def _msgs(*pairs):
    from serve.schemas import ChatMessage
    return [ChatMessage(role=r, content=c) for r, c in pairs]


def test_split_messages_extracts_question_and_history():
    from serve.conversation import split_messages
    question, history = split_messages(_msgs(
        ("system", "you are..."),
        ("user", "show active members"),
        ("assistant", "```sql\nSELECT 1\n```"),
        ("user", "now add their branch"),
    ))
    assert question == "now add their branch"
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "show active members"


def test_is_task_prompt_detects_owui_title_generation():
    from serve.conversation import is_task_prompt
    assert is_task_prompt(_msgs(
        ("user", "### Task:\nCreate a concise, 3-5 word title for the chat."),
    )) is True


def test_is_task_prompt_false_for_normal_question():
    from serve.conversation import is_task_prompt
    assert is_task_prompt(_msgs(("user", "show me active members"))) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "split_messages or task_prompt" -v`
Expected: FAIL (no `serve.conversation`).

- [ ] **Step 3: Create the module**

Create `serve/conversation.py`:

```python
"""Translate an OpenAI messages array into (question, history) and detect Open WebUI's
housekeeping ('task') prompts that must NOT be run through the SQL pipeline."""

# Open WebUI fires these at the selected model for titles/tags/queries/autocomplete.
# Primary mitigation is configuring a separate Task Model in OWUI (see OPEN_WEBUI_SETUP.md);
# this detection is a best-effort backup so they don't burn GPU on the SQL pipeline.
_TASK_MARKERS = (
    "create a concise, 3-5 word title",
    "generate 1-3 broad tags",
    "### task:",
    "generate a concise",
    "autocomplete",
)

TASK_CANNED_RESPONSE = "Schema query"


def split_messages(messages) -> tuple[str, list[dict]]:
    """Return (question, history). question = the last user message; history = the prior
    user/assistant turns (system messages dropped — this service owns the system prompt)."""
    convo = [m for m in messages if m.role in ("user", "assistant")]
    last_user = next((i for i in range(len(convo) - 1, -1, -1) if convo[i].role == "user"), None)
    if last_user is None:
        return "", []
    question = convo[last_user].content
    history = [{"role": m.role, "content": m.content} for m in convo[:last_user]]
    return question, history


def is_task_prompt(messages) -> bool:
    """True if the request looks like an Open WebUI housekeeping task (title/tag/etc.)."""
    text = "\n".join(m.content for m in messages).lower()
    return any(marker in text for marker in _TASK_MARKERS)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "split_messages or task_prompt" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serve/conversation.py tests/test_serve.py
git commit -m "feat(serve): message mapping + OWUI task-prompt detection"
```

---

## Task 5: Auth dependency (timing-safe bearer)

**Files:**
- Create: `serve/auth.py`
- Test: `tests/test_serve.py` (exercised end-to-end in Task 6; unit-check here)

- [ ] **Step 1: Write failing test**

Add to `tests/test_serve.py`:

```python
def test_auth_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("SQL_API_TOKEN", "right")
    from fastapi import HTTPException
    from serve.auth import require_auth
    with pytest.raises(HTTPException) as ei:
        require_auth(authorization="Bearer wrong")
    assert ei.value.status_code == 401


def test_auth_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("SQL_API_TOKEN", "right")
    from serve.auth import require_auth
    assert require_auth(authorization="Bearer right") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "auth" -v`
Expected: FAIL (no `serve.auth`).

- [ ] **Step 3: Create the dependency**

Create `serve/auth.py`:

```python
"""Bearer-token auth dependency. Timing-safe comparison (it's a credit union)."""
import secrets

from fastapi import Header, HTTPException, status

from serve.config import get_settings


def require_auth(authorization: str = Header(default="")) -> None:
    token = get_settings().token
    expected = f"Bearer {token}" if token else None
    if not (expected and authorization and secrets.compare_digest(authorization, expected)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token.",
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "auth" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serve/auth.py tests/test_serve.py
git commit -m "feat(serve): timing-safe bearer-token auth dependency"
```

---

## Task 6: App factory — `/health`, `/v1/models`, fail-closed startup, auth

**Files:**
- Create: `serve/app.py`
- Test: `tests/test_serve.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_serve.py`:

```python
from unittest.mock import patch
from fastapi.testclient import TestClient


def _client(monkeypatch):
    monkeypatch.setenv("SQL_API_TOKEN", "test-token")
    from serve.app import create_app
    return TestClient(create_app())


AUTH = {"Authorization": "Bearer test-token"}


def test_create_app_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("SQL_API_TOKEN", raising=False)
    from serve.app import create_app
    with pytest.raises(RuntimeError, match="SQL_API_TOKEN"):
        create_app()


def test_health_is_open(monkeypatch):
    resp = _client(monkeypatch).get("/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"


def test_models_requires_auth(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/v1/models").status_code == 401
    resp = client.get("/v1/models", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "cu-sql-assistant"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "app or health or models or fails_closed" -v`
Expected: FAIL (no `serve.app`).

- [ ] **Step 3: Create the app factory**

Create `serve/app.py`:

```python
"""FastAPI app exposing answer_question() as an OpenAI-compatible endpoint."""
import json
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from assistant.sql_assistant import answer_question
from serve import conversation
from serve.auth import require_auth
from serve.config import get_settings
from serve.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ModelCard,
    ModelList,
)


def _format_content(result: dict) -> str:
    """Assistant message = the model's explanation, with the validation verdict appended
    when validate_sql flagged the draft (so the analyst sees it in the GUI)."""
    content = result.get("explanation") or ""
    v = result.get("validation") or {}
    if not v.get("ok", True) and v.get("errors"):
        bullets = "\n".join(f"> - {e}" for e in v["errors"])
        content += (
            "\n\n---\n> ⚠️ Automated validation flagged this draft — "
            "review before running:\n" + bullets
        )
    return content


def _operational_error_message(exc: Exception) -> str:
    """Turn a pipeline error into a GUI-friendly assistant message (not a red HTTP error)."""
    msg = str(exc)
    if "build_index" in msg:
        return ("⚠️ The schema index isn't built yet. Run "
                "`python ingest/build_index.py` on the host, then retry.")
    return f"⚠️ The assistant backend couldn't draft SQL: {msg}"


def _generate_content(question: str, history: list[dict]) -> str:
    """Run the pipeline (blocking) and format the assistant message. Operational errors
    become a friendly message rather than a 500."""
    try:
        result = answer_question(question, rag_enabled=True, history=history)
    except RuntimeError as exc:
        return _operational_error_message(exc)
    return _format_content(result)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.require_token()  # fail-closed: refuse to start without a token
    app = FastAPI(title="CU SQL Assistant API")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/models", dependencies=[Depends(require_auth)])
    def list_models():
        return ModelList(data=[ModelCard(id=settings.model_id, created=int(time.time()))])

    def _json_response(content: str) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=settings.model_id,
            choices=[Choice(message=ChatMessage(role="assistant", content=content))],
        )

    def _chunk(cid, created, delta, finish=None) -> str:
        payload = {
            "id": cid, "object": "chat.completion.chunk", "created": created,
            "model": settings.model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    async def _sse(produce):
        # Emit the role chunk immediately to hold the connection, then run generation.
        cid, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
        yield _chunk(cid, created, {"role": "assistant"})
        content = await produce()
        yield _chunk(cid, created, {"content": content})
        yield _chunk(cid, created, {}, finish="stop")
        yield "data: [DONE]\n\n"

    @app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
    async def chat_completions(req: ChatCompletionRequest):
        if req.model and req.model != settings.model_id:
            raise HTTPException(status_code=404, detail=f"Unknown model '{req.model}'.")

        question, history = conversation.split_messages(req.messages)

        if conversation.is_task_prompt(req.messages):
            async def produce():
                return conversation.TASK_CANNED_RESPONSE
        elif not question.strip():
            raise HTTPException(status_code=400, detail="No user message found.")
        else:
            async def produce():
                return await run_in_threadpool(_generate_content, question, history)

        if req.stream:
            return StreamingResponse(_sse(produce), media_type="text/event-stream")
        return _json_response(await produce())

    return app
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "app or health or models or fails_closed" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serve/app.py tests/test_serve.py
git commit -m "feat(serve): app factory with health, models, auth, fail-closed startup"
```

---

## Task 7: `/v1/chat/completions` — generation, validation surfacing, errors

**Files:**
- Modify: `tests/test_serve.py` (behavior already implemented in Task 6; this task locks it with tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_serve.py`:

```python
def test_chat_completion_returns_validation_verdict(monkeypatch):
    client = _client(monkeypatch)
    fake = {"explanation": "Here is the query.",
            "validation": {"ok": False, "errors": ["Unknown column: member_id"], "warnings": []}}
    with patch("serve.app.answer_question", return_value=fake) as m:
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "model": "cu-sql-assistant",
            "messages": [{"role": "user", "content": "member growth"}],
        })
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "Unknown column: member_id" in content and "validation flagged" in content
    # mapping: last user message becomes the question
    assert m.call_args.args[0] == "member growth"


def test_chat_completion_maps_history(monkeypatch):
    client = _client(monkeypatch)
    with patch("serve.app.answer_question", return_value={"explanation": "ok", "validation": {"ok": True, "errors": []}}) as m:
        client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [
                {"role": "user", "content": "show active members"},
                {"role": "assistant", "content": "```sql\nSELECT 1\n```"},
                {"role": "user", "content": "add their branch"},
            ],
        })
    assert m.call_args.args[0] == "add their branch"
    assert m.call_args.kwargs["history"][0]["content"] == "show active members"


def test_chat_completion_unknown_model_404(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/v1/chat/completions", headers=AUTH, json={
        "model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 404


def test_chat_completion_task_prompt_short_circuits(monkeypatch):
    client = _client(monkeypatch)
    with patch("serve.app.answer_question") as m:
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "### Task:\nCreate a concise, 3-5 word title"}]})
    assert resp.status_code == 200
    m.assert_not_called()


def test_chat_completion_index_missing_is_friendly(monkeypatch):
    client = _client(monkeypatch)
    with patch("serve.app.answer_question", side_effect=RuntimeError("Chroma ... run build_index.py")):
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "members"}]})
    assert resp.status_code == 200
    assert "index isn't built" in resp.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 2: Run to verify pass (logic exists from Task 6)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py -k "chat_completion" -v`
Expected: PASS. If `test_chat_completion_maps_history` fails because `history` is passed positionally, confirm `_generate_content` calls `answer_question(question, rag_enabled=True, history=history)` (kwarg) as written in Task 6.

- [ ] **Step 3: Commit**

```bash
git add tests/test_serve.py
git commit -m "test(serve): cover chat completions mapping, validation, errors"
```

---

## Task 8: Streaming (SSE) path

**Files:**
- Modify: `tests/test_serve.py` (SSE behavior implemented in Task 6)

- [ ] **Step 1: Write failing test**

Add to `tests/test_serve.py`:

```python
def test_chat_completion_streaming_emits_sse(monkeypatch):
    client = _client(monkeypatch)
    fake = {"explanation": "SELECT done", "validation": {"ok": True, "errors": []}}
    with patch("serve.app.answer_question", return_value=fake):
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "members"}], "stream": True})
    assert resp.status_code == 200
    body = resp.text
    assert '"role": "assistant"' in body          # early role chunk
    assert "SELECT done" in body                    # content chunk
    assert "data: [DONE]" in body                   # terminator
```

- [ ] **Step 2: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py::test_chat_completion_streaming_emits_sse -v`
Expected: PASS.

- [ ] **Step 3: Run the full offline suite**

Run: `.venv/Scripts/python.exe -m pytest -m "not integration" -q`
Expected: PASS (all tasks so far green).

- [ ] **Step 4: Commit**

```bash
git add tests/test_serve.py
git commit -m "test(serve): cover SSE streaming envelope"
```

---

## Task 9: `python -m serve` entrypoint + manual smoke test

**Files:**
- Create: `serve/__main__.py`
- Test: `tests/test_serve.py` (import smoke) + a manual integration check

- [ ] **Step 1: Write failing test**

Add to `tests/test_serve.py`:

```python
def test_main_module_exposes_main(monkeypatch):
    monkeypatch.setenv("SQL_API_TOKEN", "test-token")
    import serve.__main__ as m
    assert callable(m.main)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py::test_main_module_exposes_main -v`
Expected: FAIL (no `serve/__main__.py`).

- [ ] **Step 3: Create the entrypoint**

Create `serve/__main__.py`:

```python
"""Run the API as a host process: `python -m serve`."""
import uvicorn

from serve.app import create_app
from serve.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_serve.py::test_main_module_exposes_main -v`
Expected: PASS.

- [ ] **Step 5: Manual smoke test (requires Ollama running + index built)**

```powershell
$env:SQL_API_TOKEN = "dev-token"
.venv/Scripts/python.exe -m serve
```
In another shell:
```powershell
curl http://localhost:8000/v1/models -H "Authorization: Bearer dev-token"
curl http://localhost:8000/v1/chat/completions -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"How many members joined in the last year?"}]}'
```
Expected: model list with `cu-sql-assistant`; a grounded T-SQL draft in the completion. Verify a deliberately bad ask (e.g. member losses over time) surfaces a validation block.

- [ ] **Step 6: Commit**

```bash
git add serve/__main__.py tests/test_serve.py
git commit -m "feat(serve): python -m serve entrypoint"
```

---

## Task 10: Document the local-API path in OPEN_WEBUI_SETUP.md

**Files:**
- Modify: `docs/OPEN_WEBUI_SETUP.md`

- [ ] **Step 1: Add a new top section** (after the intro, before the legacy manual-RAG sections) describing the single-source-of-truth path:

```markdown
## A. Recommended: connect Open WebUI to the local SQL-assistant API

This routes the GUI through the exact same pipeline as the scripted path (retrieval +
system prompt + the deterministic `validate_sql` gate). It supersedes the manual RAG /
system-prompt configuration in sections 1–3 below for this model.

1. **Run the API on the host** (next to Ollama):
   ```powershell
   $env:SQL_API_TOKEN = "<choose-a-strong-token>"
   python -m serve   # listens on 0.0.0.0:8000
   ```
2. **Add an OpenAI connection** in Open WebUI: Admin Panel → Settings → Connections →
   OpenAI API → **Base URL** `http://host.docker.internal:8000/v1`, **API key** =
   the same `SQL_API_TOKEN`. The model `cu-sql-assistant` then appears in the dropdown.
3. **Set a separate Task Model (required).** Open WebUI uses the selected model for
   title/tag/search-query/autocomplete generation. If it uses `cu-sql-assistant`, those
   housekeeping prompts run through the SQL pipeline (wasted GPU, nonsense titles). Under
   Admin Panel → Settings → Interface, set the **Task Model** to a plain Ollama model
   (e.g. `qwen2.5-coder:14b`) and turn **Autocomplete Generation OFF**. (The API also
   best-effort short-circuits these prompts, but the Task Model setting is the real fix.)
4. Chat with `cu-sql-assistant`. No knowledge base, RAG template, or system prompt needs
   to be configured in the UI — the API owns all of it.

> Sections 1–3 (manual RAG template, knowledge base, pasted system prompt) remain as a
> **legacy** fallback for running directly against an Ollama base model without the API.
> Prefer section A — it cannot drift from the scripted path.
```

- [ ] **Step 2: Verify links/instructions are internally consistent** (port 8000, token name `SQL_API_TOKEN`, `host.docker.internal` matching the existing Ollama setup at line ~35).

- [ ] **Step 3: Commit**

```bash
git add docs/OPEN_WEBUI_SETUP.md
git commit -m "docs(openwebui): connect via local SQL-assistant API (single source of truth)"
```

---

## Self-review

**1. Spec coverage:**
- OpenAI-compatible `/v1/chat/completions` + `/v1/models` → Tasks 6–8. ✓
- Non-streaming generation + SSE wire envelope w/ early role chunk → Task 6 (`_sse`), Task 8. ✓
- Multi-turn history + retrieval keyed on recent user messages → Task 1. ✓
- Host-process runtime, no Ollama-URL change → Task 9; Task 1 leaves Ollama client untouched. ✓
- Bearer auth, fail-closed → Tasks 2, 5, 6. ✓
- Validation verdict surfaced → Task 6 (`_format_content`), Task 7. ✓
- OWUI task-model gotcha (detection + docs) → Tasks 4, 7, 10. ✓
- Error policy (protocol HTTP codes vs friendly 200) → Tasks 6, 7. ✓
- Offline tests → Tasks 1–9; full-suite gate in Task 8. ✓
- Docs supersede manual config → Task 10. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code. Token-budget history trimming is intentionally a count-cap (`HISTORY_MAX_MESSAGES`), a complete implementation per the spec's "start conservative" — not a placeholder.

**3. Type consistency:** `answer_question(..., history=...)`, `Settings.require_token()`, `split_messages()→(question, history)`, `is_task_prompt()`, `_format_content`/`_generate_content`/`_operational_error_message`, schema field names (`messages`, `stream`, `choices[].message.content`) are used identically across Tasks 1–10. ✓

## Notes for the implementer
- Run every test with the project venv: `.venv/Scripts/python.exe -m pytest -m "not integration" -q`.
- The new deps (`fastapi`, `uvicorn`, `httpx`) are added to `requirements.txt` in Task 2, so the offline CI gate installs them automatically.
- Do **not** modify `assistant/validate.py` or the Ollama client base URL — the host-process deployment reaches Ollama at `localhost:11434` unchanged.
