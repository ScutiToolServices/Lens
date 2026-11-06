# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" \
    LENS_DATA_DIR=/data LENS_HOST=0.0.0.0 \
    LENS_FAST_TESSDATA_DIR=/opt/ocr-models/fast LENS_ACCURATE_TESSDATA_DIR=/opt/ocr-models/accurate \
    OMP_THREAD_LIMIT=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home ocr \
    && mkdir /data && chown ocr /data
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && uv run --no-sync python -m src.models
COPY MODEL-LICENSE.txt /opt/ocr-models/LICENSE
COPY MODEL-NOTICE.md /opt/ocr-models/NOTICE.md
COPY web ./web
USER ocr
EXPOSE 8093
CMD ["python", "-m", "src.run"]
