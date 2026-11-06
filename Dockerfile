# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" \
    LENS_DATA_DIR=/data LENS_HOST=0.0.0.0
RUN useradd --system --uid 10001 --create-home ocr \
    && mkdir /data && chown ocr /data
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY web ./web
USER ocr
EXPOSE 8093
CMD ["python", "-m", "src.run"]
