# Lens

CPU-only image-region OCR service for Citadel extensions, with HTTP and MCP on
port **8093**. `fast` uses standard English `tessdata_fast`; `accurate` uses
English `tessdata_best`. **Every extraction request accepts `mode`; omission
always defaults to `accurate`.** No GPU, LLM, hosted OCR API, or inference network
call is involved. Accurate names a model choice, not a guarantee of fewer errors.

This is separate from sibling Reader, which uses a remote GPU model.
Citadel's existing image CLI remains available. Extension registration is a later step.

## Windows setup

Run from `D:\User\Documents\Programming\AI\ToolServices\Lens`:

```powershell
uv sync
# Install Tesseract separately if not installed already:
# winget install --id UB-Mannheim.Lens --exact
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
uv run python -m src.models
uv run python -m src.run
```

The explicit model setup command downloads both official English models and
checks pinned SHA-256 digests before atomically installing them in
`.data/models/fast` and `.data/models/accurate`. It never installs the Tesseract
binary. Existing valid model files are reused. Missing binary/models yield
readiness false and clear extraction errors; accurate never silently falls back
to fast. Both models must be ready for `/health` readiness to be true.

Models are selected with per-call `--tessdata-dir` arguments, so simultaneous
fast/accurate requests are isolated even if `TESSDATA_PREFIX` is set elsewhere.
Only English is currently provided. Install additional languages only when API
support is added; changing `TESSDATA_PREFIX` does not select these service models.

With pytesseract 0.3.13 on Windows, model directory paths must contain no spaces
(its config parser preserves literal quote characters). The default project path
works. If your checkout path has spaces, set `LENS_FAST_TESSDATA_DIR` and
`LENS_ACCURATE_TESSDATA_DIR` to separate whitespace-free directories before model
setup and startup. Uploaded image filenames may contain spaces. Linux/Docker
model directories support spaces through normal POSIX argument quoting.

The service reads process environment only; it does not load a local `.env` file.
For authenticated use, set `INTERNAL_API_TOKEN`; `LENS_HOST=0.0.0.0` without it
is refused. The default is loopback-only.

## HTTP contract

All `/api/*` calls need `X-Requester-Username`; when configured, also send
`X-Internal-Token`. The trusted Citadel server supplies requester identity.
Clients possessing the internal token can assert usernames; do not expose that
token to untrusted clients. Upload IDs are scoped to the requester, and a different
requester's ID returns 404. Filenames are labels, never server filesystem paths.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | Public liveness, readiness and mode availability |
| GET | `/api/modes` | Model choices, accurate default and availability |
| POST | `/api/files` | Raw PNG/JPEG/WebP bytes; optional `X-Filename` |
| POST | `/api/extract` | JSON extraction request; final JSON response |
| POST | `/api/extract/stream` | Same JSON request; completed-region SSE stream |
| POST | `/mcp` | MCP Streamable HTTP transport |

Upload returns `{file_id, width, height, size_bytes, expires_at, message}`.
Upload choices in the shared admin playground are echoed as `mode` and
`preprocess` for its extraction follow-up; uploads do not set extraction defaults.

Extraction request:

```json
{
  "file_id": "UPLOAD_ID",
  "mode": "accurate",
  "regions": [[10, 200, 875, 433]],
  "preprocess": true
}
```

`mode` accepts exactly `fast` or `accurate`. Unknown mode is 422. `regions` is
optional; omitted/empty means the whole image. Boxes use integer pixels and
exclusive right/bottom edges: `0 <= x0 < x1 <= width`, likewise for y. All boxes
are validated before recognition starts. `preprocess` defaults false and performs
only grayscale plus autocontrast. Animated/multipage images and PDFs are rejected.

Response:

```json
{
  "file_id": "UPLOAD_ID",
  "mode": "accurate",
  "model": "tessdata_best/eng",
  "regions": [{"index": 0, "region": [10, 200, 875, 433], "text": "A woman goes to work.", "confidence": 88.6}],
  "text": "A woman goes to work.",
  "cached": false,
  "message": "Extracted 1 region(s) using accurate CPU OCR."
}
```

Confidence is the mean of valid nonempty Tesseract word scores, 0–100, or `null`
when no words are recognized. It is not a calibrated probability of correctness.
Final regions and combined text preserve input order. Cache keys include owner,
image, model weights, mode, regions and preprocessing; both modes can stay cached.

Errors use `{error, message}`: 400 invalid image/boxes, 401 missing identity/token,
404 missing/expired/other-owner upload, 413 upload/request/quota limit, 422 request
schema, 503 capacity/model/engine/storage/time limit. Messages do not disclose
server paths or Tesseract diagnostics. Retrying with a smaller crop or fast mode
can reduce processing time. No automatic cross-model retry occurs.

### PowerShell example

Run with the server started in another terminal:

```powershell
$headers = @{ 'X-Requester-Username' = 'local-test' }
# When authentication is enabled:
# $headers['X-Internal-Token'] = $env:INTERNAL_API_TOKEN
$upload = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8093/api/files' `
    -Headers $headers -ContentType 'application/octet-stream' -InFile 'C:\images\sample.png'
$body = @{ file_id = $upload.file_id; mode = 'accurate'; regions = @(@(10,200,875,433)); preprocess = $true } |
    ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8093/api/extract' `
    -Headers $headers -ContentType 'application/json' -Body $body
```

Set `mode = 'fast'` for the fast model. Remove mode entirely for accurate default.
Use boxes within your own image dimensions.

### Nonblocking Python client

```python
import asyncio
import os
from pathlib import Path

import httpx


async def main():
    headers = {"X-Requester-Username": "local-test"}
    if token := os.environ.get("INTERNAL_API_TOKEN"):
        headers["X-Internal-Token"] = token
    data = await asyncio.to_thread(Path("sample.png").read_bytes)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8093", headers=headers, timeout=120) as client:
        upload = await client.post("/api/files", content=data)
        upload.raise_for_status()
        file_id = upload.json()["file_id"]
        for mode in ("fast", "accurate"):
            response = await client.post("/api/extract", json={"file_id": file_id, "mode": mode})
            response.raise_for_status()
            print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
```

## Streaming

`POST /api/extract/stream` sends Server-Sent Events:

1. `start`: selected mode, region count and whether results are cached.
2. `region`: `{index, region, text, confidence}` in its `result` field, as each crop finishes.
3. `complete`: full ordinary extraction response, preserving input order.

Once HTTP 200 starts, a later failure produces `error` and **no `complete`**.
Earlier region results remain partial; clients must require `complete` before
treating the job as successful. Invalid identity, model, boxes and initial capacity
fail with normal HTTP status codes before streaming begins. Streaming request
schema errors are also ordinary JSON responses.

This is real **region-level streaming**, not word/token streaming. One whole-image
region yields its text after that image finishes. Multiple crops can complete out
of order; use `index`. Cached results stream immediately. Disable proxy buffering
and keep upstream read timeouts above `LENS_TIMEOUT_S`. Disconnect cancellation stops
scheduling further regions; already-started OCR threads drain and retain their CPU
slots until they exit. No incomplete result is cached.

Async streaming client, after uploading and obtaining `file_id`:

```python
async with client.stream("POST", "/api/extract/stream", json={"file_id": file_id, "mode": "accurate"}) as response:
    response.raise_for_status()
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            print(line[6:])
```

## MCP and future Citadel extension

Tools:

- `tool_ocr_modes()`: lists fast/accurate choices, default and availability.
- `tool_ocr_extract(file_id, mode="accurate", regions=[], preprocess=false)`:
  same service, ownership, quota, cache, CPU bounds and result as HTTP.

Citadel forwards `_meta.requester.username`. For MCP progress, the client sends
`_meta.progressToken`; the service emits monotonically increasing completed-region
progress. MCP returns one final structured extraction result; intermediate text
is delivered through the HTTP SSE endpoint, not through progress messages.
MCP uses sessions to support progress notifications. Keep MCP requests for a
session on the same service process when deploying behind a load balancer.

Later Armory extension entry (example only; nothing in Citadel has been changed):

```json
{
  "tesseract_ocr": {
    "label": "Lens",
    "description": "CPU image OCR. Choose fast or accurate per request; default accurate.",
    "url": "http://127.0.0.1:8093/mcp",
    "headers": {"X-Internal-Token": "${INTERNAL_API_TOKEN}"},
    "forward_requester": true
  }
}
```

For Compose peers on `citadel_core`, use `http://tesseract-ocr:8093/mcp` instead.
The upload handoff must POST image bytes to this service and pass its returned
file ID to the extension. IDs from Reader or other services are unrelated.
Display the mode choice in Citadel when you want a user-facing choice; API/MCP
requests themselves do not open an interactive prompt.

## Admin and operational parity

Set `LENS_ADMIN_PASSWORD`, restart, then open `/admin/`. Shared peer admin shell
provides status, per-requester usage/errors/average latency, editable limits and
an upload playground with fast/accurate choice. Admin API uses `X-Admin-Password`,
separate from the ordinary internal token. Saved settings live in
`.data/settings.json`; file access runs in worker threads. Concurrency and admitted
job limits are marked restart-required. Retention changes apply to new uploads.

The model-service routing section has no remote slots: both OCR models run here.
No unused remote GPU/LLM connectors were added. Usage resets on restart.

Uploads and completed cached results are scoped to requester and retained for
24 hours. Quota counts uploaded bytes plus cached JSON. Duplicate uploads reuse
their ID and expiry without counting twice. SQLite expiry sweep runs on startup,
each upload, and every 60 seconds; expired IDs are unusable immediately. SQLite
reuses released database pages; its file size does not shrink after every expiry.
Models and uploads stay in `.data` and are not committed or packaged into source.

| Environment | Default | Purpose |
| --- | --- | --- |
| `LENS_HOST`, `LENS_PORT` | `127.0.0.1`, `8093` | Bind address |
| `INTERNAL_API_TOKEN` | empty | Required on non-loopback binds |
| `LENS_ADMIN_PASSWORD` | empty | Admin disabled until set |
| `TESSERACT_CMD` | `tesseract` | Binary path or PATH-resolved command |
| `LENS_DATA_DIR` | project `.data` | SQLite, models and saved settings |
| `LENS_FAST_TESSDATA_DIR` | `.data/models/fast` | Explicit fast English model directory |
| `LENS_ACCURATE_TESSDATA_DIR` | `.data/models/accurate` | Explicit best English model directory |
| `LENS_MAX_UPLOAD_MB` | `10` | Per-upload byte bound |
| `LENS_MAX_PIXELS` | `16000000` | Decoded pixel bound |
| `LENS_MAX_REGIONS` | `32` | Boxes per extraction, schema maximum 256 |
| `LENS_MAX_RESULT_CHARS` | `250000` | Combined OCR output character cap |
| `LENS_TIMEOUT_S` | `110` | Job deadline, including queued worker time |
| `LENS_TTL_HOURS` | `24` | Retention for new uploads and attached cache |
| `LENS_QUOTA_MB` | `200` | Stored bytes per requester |
| `LENS_CONCURRENCY` | `2` | Global CPU OCR slots, shared by both modes |
| `LENS_MAX_JOBS` | `4` | Admitted jobs including upload validation; excess is 503 |

One process owns these limits. Use one uvicorn worker; replicas each have their
own CPU pool. In containers `OMP_THREAD_LIMIT=1` also bounds internal Tesseract
OpenMP threads. Network server connection concurrency is capped at 32.

## Docker deployment

```powershell
$env:INTERNAL_API_TOKEN = 'choose-a-service-token'
$env:LENS_ADMIN_PASSWORD = 'choose-an-admin-password'
docker compose up -d --build
```

The external `citadel_core` network must exist (start Citadel stack first, or
create that network for standalone testing). Image installs CPU Tesseract and
both verified model files during build, runs as an unprivileged user, and mounts
`ocr_data` for runtime uploads/settings. No GPU runtime or host Python required.
Default published port is loopback-only; set `LENS_BIND` for your deployment.
Model downloads require network during setup/build; OCR works offline afterward.

Docker daemon was unavailable on the development machine, so image build and
container runtime remain unverified. Native Windows CPU paths are tested.

Current dependencies emit two warnings during tests (Starlette's deprecated
AnyIO portal alias and MCP/Pydantic's lifespan annotation). MCP 1.28.0 can also
log `ClosedResourceError` from its standalone SSE writer when a client closes a
session after receiving a successful result; this was observed during the real
MCP screenshot smoke test. Request results and progress tests still pass. These
upstream diagnostics are not hidden or treated as OCR failures.

## Tests

```powershell
uv run pytest -q -rs
uv run ruff check src tests
```

Most tests use a deterministic engine and need no binary/model. Real generated-text
tests cover both models after setup; skip with a reason when prerequisites are
missing. Tests exercise HTTP and real MCP handshakes, live SSE delivery before
later regions finish, auth/ownership, mode isolation/defaults, exact crops,
confidence, cache, quota, expiry, thread limits and cancellation.

## Model sources and license

English weights come from official [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast)
and [tessdata_best](https://github.com/tesseract-ocr/tessdata_best), under Apache-2.0.
See [upstream license](https://github.com/tesseract-ocr/tessdata_best/blob/main/LICENSE).
Full model license and attribution ship in `MODEL-LICENSE.txt` and `MODEL-NOTICE.md`.
`src/models.py` pins file hashes; intentional weight upgrades must update hashes
and rerun the recognition comparison. For binary installation see
[Tesseract's installation documentation](https://tesseract-ocr.github.io/tessdoc/Installation.html).
