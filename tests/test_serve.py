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
