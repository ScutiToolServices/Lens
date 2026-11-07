# Deploying Lens

Lens is one HTTP and MCP service (image-region OCR) on port 8093. It runs no model itself: it needs a TesseractModel connection saved on its admin page.

## Requirements

- Docker with Compose v2, or native Windows with uv.
- A running TesseractModel service and a token for Lens made on its `/admin/` page.
- The external `citadel_core` network, so Armory and ember_api can reach Lens.

## Settings

In `.env` next to `docker-compose.yml` (copy `.env.example`):

| Variable | Default | Effect |
|---|---|---|
| `INTERNAL_API_TOKEN` | empty | Shared token for `/mcp` and `/api/*`. Required when `LENS_HOST` is not loopback. |
| `LENS_HOST` / `LENS_PORT` | `127.0.0.1` / `8093` | Listen address (Compose sets the host itself). |
| `LENS_BIND` | see `.env.example` | Docker only: the address the published port listens on. |
| `LENS_ADMIN_PASSWORD` | empty | Unlocks `/admin/`. Empty = page off, so no model connection can be saved. |

Everything else (limits, data folder, model connection) is set on the admin page. See `docs/guide-web-ui.md`.

## Start

```bash
docker compose up -d --build
curl http://127.0.0.1:8093/health
```

Then open `/admin/`, save a connection to the TesseractModel service under **Model services**, and press **Test connection**.

## Updating

`docker compose up -d --build`. Settings, saved connections and stored data live in the data volume and survive it.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Calls fail with "not connected" | No model service connection is saved on the admin page yet. |
| 401 | The caller sends no `INTERNAL_API_TOKEN`, or the wrong one. |
| The service refuses to start | `LENS_HOST` is not loopback and `INTERNAL_API_TOKEN` is empty. |

## Releasing

A plain publish (`tools\deploy.bat` option 1) only updates the `live` branch. For a release set `VERSION` (and `pyproject.toml` to the same number), commit, then run `tools\deploy.bat` option R or `py tools\publish_live.py --release`. `tools\make_zip.bat` then builds `zip_versions\Lens-<VERSION>.zip`.
