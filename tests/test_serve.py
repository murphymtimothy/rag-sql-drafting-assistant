import pytest


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
