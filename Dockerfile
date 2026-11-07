# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" \
    SERVICE_DATA_DIR=/data SERVICE_HOST=0.0.0.0 SERVICE_PORT=29403
WORKDIR /app

RUN useradd --system --uid 10001 --create-home ocr \
    && mkdir /data && chown ocr /data

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY web ./web
RUN uv sync --frozen --no-dev --no-editable
USER ocr

EXPOSE 29403
# No OCR runs here: save a OCR_Tesseract_Model connection on the admin page.
CMD ["python", "-m", "src.run"]
