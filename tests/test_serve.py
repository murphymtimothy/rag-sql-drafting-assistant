import pytest
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


def test_request_ignores_extra_fields_and_defaults_stream_false():
    from serve.schemas import ChatCompletionRequest
    req = ChatCompletionRequest.model_validate({
        "model": "cu-sql-assistant",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.7,  # extra OpenAI field OWUI sends — must be ignored
    })
    assert req.stream is False
    assert req.messages[0].content == "hi"


def test_require_token_raises_when_unset(monkeypatch):
    monkeypatch.delenv("SQL_API_TOKEN", raising=False)
    from serve.config import Settings
    with pytest.raises(RuntimeError, match="SQL_API_TOKEN"):
        Settings().require_token()


def test_require_token_returns_when_set(monkeypatch):
    monkeypatch.setenv("SQL_API_TOKEN", "secret")
    from serve.config import Settings
    assert Settings().require_token() == "secret"


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


def test_chat_completion_streaming_emits_sse(monkeypatch):
    client = _client(monkeypatch)
    fake = {"explanation": "SELECT done", "validation": {"ok": True, "errors": []}}
    with patch("serve.app.answer_question", return_value=fake):
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "members"}], "stream": True})
    assert resp.status_code == 200
    body = resp.text
    assert '"role": "assistant"' in body
    assert "SELECT done" in body
    assert "data: [DONE]" in body
