"""Run the API as a host process: `python -m serve`."""
import uvicorn

from serve.app import create_app
from serve.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
