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
