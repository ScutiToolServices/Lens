# CPU image OCR tool service

## Intent and scope

Create a standalone CPU OCR service in `AI/ToolServices/Lens`, port 8093, for later Citadel extension integration. Preserve the existing GPU-backed Reader service and Citadel CLI. Accept PNG, JPEG and WebP uploads and optional integer pixel regions; an omitted/empty region list means the whole image. Keep preprocessing to grayscale plus autocontrast.

## Request contract

Every HTTP/MCP extraction accepts `mode: fast | accurate`, default `accurate`. The user's clarification places this choice in requests sent by Citadel, rather than requiring an interactive question. Fast selects standard fast English Tesseract weights; accurate selects official tessdata_best English weights. Explicit per-call tessdata paths prevent concurrent requests from selecting each other's weights. Accurate is a model name, not an accuracy guarantee.

## Approaches

Extending Reader would mix its remote GPU engine and document parsing with a separate CPU image tool. A standalone service following the same MCP/HTTP/admin conventions is the chosen implementation: independent deployment and no changes to peers. A shared runtime package would require changing existing projects and is deferred; reuse unchanged peer runtime/admin assets locally.

## API and streaming

`POST /api/files` accepts bounded raw image bytes with filename and requester headers. `POST /api/extract` accepts an owned file ID, mode, regions and preprocessing flag. `POST /api/extract/stream` returns SSE start, region, complete or sanitized error events; each region includes its input index. Normal results preserve input order. MCP `/mcp` provides extraction and mode discovery with requester metadata and progress notifications. OCR is batch per crop: no token/word streaming, no fake progressive text. A one-region request has no text until that region finishes.

## Reused service features

Internal-token authentication, refusal of exposed unauthenticated startup, owner isolation, 24-hour retention, per-owner quota, option/model-aware persistent cache, periodic expiry cleanup, health/readiness, admin status/usage/live limits, shared upload playground, Docker/Compose, documented extension registration and CPU-only deployment. SQLite transactions make quota, upload deduplication, cache and expiry consistent; no arbitrary server path input or remote model routing. Limits: 10 MiB uploads, 16 million decoded pixels, 32 regions, 4 admitted jobs, 2 global OCR slots and 110-second job deadline by default. Bound worker and SSE queues; cancellation drains threads before releasing their slots.

## Modules and verification

Separate contracts/config/options, model installation, engine, store, service orchestration, HTTP/MCP glue. Download explicit English fast/best weights with checksum verification into runtime data; missing models fail clearly instead of falling back. Tests cover mode defaults/isolation, exact crops, confidence, malformed inputs, ownership/auth, cache keys, quota/expiry, streaming order/errors/cancellation, admin settings, MCP handshake, and real CPU recognition. Compare the user's screenshot in both modes. Docker build is conditional on daemon availability; report untested deployment explicitly.

## Non-goals

PDF/layout/table parsing, handwriting, GPU engines, LLM/API inference, remote model services, automatic Tesseract binary installation, and Citadel-side extension changes. Uploaded text is data, never instructions.
