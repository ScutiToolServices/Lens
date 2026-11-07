# Lens: without Docker, on Windows

Run Lens directly with Python: one process, no load balancer, listening on `127.0.0.1:8093`.

## Requirements

- Windows with uv (`winget install astral-sh.uv`).
- A running OCR_Tesseract_Model service and a token for Lens made on its `/admin/` page.

## Start

`run.bat` loads `.env` in this folder (copy `.env.example`) through `--dotenv` and prints the names it loaded, never the values; a real environment variable wins over it. A plain `uv run python -m src.run` does not read `.env`. Set variables in `.env` or in the environment before starting. The variables are listed under Settings in [guide-docker-same-device.md](guide-docker-same-device.md#settings); the ones that name Docker or Compose do not apply here.

Double-click `run.bat`, or run it in a terminal from `Lens\`. Choose **1 Run the service** in the menu, or run `run.bat run` to skip the menu. It runs `uv sync` to create or update `.venv`, then starts `python -m src.run`.

```bash
uv sync
uv run python -m src.run
```

## Check

```bash
curl http://127.0.0.1:8093/health
```

Then open `/admin/`, save a connection to the OCR_Tesseract_Model service under **Model services**, and press **Test connection**.

## Stop

Ctrl+C in the terminal. Do not run this and the Docker stack together: both use port 8093.

## Tests

```bash
uv run pytest -q
```
