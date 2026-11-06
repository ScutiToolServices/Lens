"""Start the standalone CPU OCR service using environment configuration."""

import sys

import uvicorn

from src.app import build_app
from src.config import load_settings


def main():
    try:
        settings = load_settings()
        app = build_app(settings)
    except ValueError as error:
        sys.exit(f"Lens configuration error: {error}")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", limit_concurrency=32)


if __name__ == "__main__":
    main()
