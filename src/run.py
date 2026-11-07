"""Start the standalone CPU OCR service using environment configuration."""

import sys

import uvicorn

from src.app import build_app
from src.config import PROJECT_DIR, load_settings
from src.runtime import load_env_file


def serve(app, **options) -> None:
    """uvicorn.run, plus the admin page link under uvicorn's own "running on" line."""

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            host = "127.0.0.1" if self.config.host in ("0.0.0.0", "::") else self.config.host
            print(f"INFO:     Admin page: http://{host}:{self.config.port}/admin/", flush=True)

    Server(uvicorn.Config(app, **options)).run()


def main():
    if "--dotenv" in sys.argv[1:]:  # run.bat asks for it; Docker and the tests never read .env
        env_file = PROJECT_DIR / ".env"
        if env_file.is_file():
            names = load_env_file(env_file)
            print(f".env: loaded {', '.join(names) or 'no variables'} (names only; a real environment variable wins)", flush=True)
        else:
            print(".env: no file in the service folder", flush=True)
    try:
        settings = load_settings()
        app = build_app(settings)
    except ValueError as error:
        sys.exit(f"Lens configuration error: {error}")
    serve(app, host=settings.host, port=settings.port, log_level="info", limit_concurrency=32)


if __name__ == "__main__":
    main()
