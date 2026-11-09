# Purpose

**Kind:** image regions → text

**Tags:** `cpu`, `mcp`, `http`, `streaming`

| | |
|---|---|
| Input | An uploaded PNG, JPEG or WebP (at most 10 MB and 16 million pixels) and an extraction request: up to 32 regions (boxes) and a `mode`, `fast` or `accurate` (accurate when omitted). Over `POST /api/extract`, `POST /api/extract/stream` or the MCP tools `tool_ocr_extract` and `tool_ocr_modes`. |
| Output | The text of every region, in input order, as a final JSON reply or as a server-sent stream of completed regions. |
| Needs | `OCR_Tesseract_Model`, one `ocr` connection on the admin page. Its model fingerprint is part of Lens's own result cache key. |
| Runs on | CPU. Holds no model; Lens decodes, cuts and preprocesses the regions and sends one crop per call. |

**Use for:** extracting text from parts of an image, with a speed or accuracy choice per request.
**Not for:** whole PDFs and multi-page documents (see `Reader`), handwriting, languages other than English.
