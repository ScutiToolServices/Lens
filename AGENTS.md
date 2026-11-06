# Lens

CPU-only image-region OCR service for Citadel extensions. Read `README.md` for API contracts and deployment.

- Use `uv sync`, `uv run pytest -q`, and `uv run python -m src.run` here.
- `mode` is per HTTP/MCP request: `fast` uses tessdata_fast, `accurate` uses tessdata_best. Omitted mode is always accurate.
- Each OCR call passes its model directory explicitly. Process environment must never change to select request models.
- Keep OCR behind `OcrEngine`; file, SQLite, Pillow and pytesseract work runs in threads. Cancellation drains active threads before releasing CPU slots or closing images.
- Streaming emits completed regions, not individual words. Final results preserve input order.
- Upload ownership comes from HTTP `X-Requester-Username` or MCP `_meta.requester.username`; internal token protects both transports. Public errors contain no filesystem paths or backend exception text.
- `src/runtime.py`, `src/admin_api.py`, and shared web assets originate in sibling Reader. Keep unchanged shared copies compatible; service-specific options belong in `options.py` and playground descriptors in `app.py`.
- Models are installed explicitly with `uv run python -m src.models`, never during OCR requests. Runtime data and model weights stay untracked.
- Citadel extension registration is documented, not performed by this project.
