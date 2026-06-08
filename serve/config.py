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
