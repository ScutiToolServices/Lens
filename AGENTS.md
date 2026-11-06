# Lens

Image-region OCR service for Citadel extensions. The recognition runs on a `TesseractModel` service (`AI/ModelServices/TesseractModel`); Lens cuts regions and keeps uploads, jobs, quota and its result cache. Read `README.md` for API contracts and deployment.

- Use `uv sync`, `uv run pytest -q`, and `uv run python -m src.run` here.
- Data folder: `Settings.data_dir` holds the result cache and uploads; the admin setting `data_path` (restart, `src/config.py` `with_saved_data_path`) moves it at the next start and keeps `settings.json` and `backends.json` in `Settings.state_dir` (the first folder). No `.env` variable; `LENS_DATA_DIR` is read only as the base folder (Docker).
- `mode` is per HTTP/MCP request: `fast` uses tessdata_fast, `accurate` uses tessdata_best. Omitted mode is always accurate.
- Each OCR call names its mode explicitly (`RemoteOcrEngine` in `src/engine.py` sends it as a query option). The model service address and token are the `ocr` slot saved on the admin page (`.data/backends.json`, never sent back, read on every call); there is no environment variable for them and no local engine, so `LENS_ADMIN_PASSWORD` is needed to configure it. The cache key includes the service's fingerprint of the model file.
- Keep OCR behind `OcrEngine`; file, SQLite, Pillow and the blocking model-service calls run in threads. Cancellation drains active threads before releasing CPU slots or closing images.
- Streaming emits completed regions, not individual words. Final results preserve input order.
- Upload ownership comes from HTTP `X-Requester-Username` or MCP `_meta.requester.username`; internal token protects both transports. Public errors contain no filesystem paths or backend exception text.
- `src/runtime.py`, `src/admin_api.py`, and shared web assets originate in sibling Reader. Keep unchanged shared copies compatible; service-specific options belong in `options.py` and playground descriptors in `app.py`.
- Lens installs no model. Weights, the Tesseract program and the license notices live in `TesseractModel`. Runtime data stays untracked.
- Citadel extension registration is documented, not performed by this project.
