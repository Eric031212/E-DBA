# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --extra postgres

RUN useradd --create-home --uid 10001 edba && mkdir -p /app/var && chown -R edba /app/var
USER edba
ENV PATH="/app/.venv/bin:$PATH" EDBA_UPLOAD_DIR=/app/var/uploads
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz')"
CMD ["sh", "-c", "alembic upgrade head && edba init && uvicorn edba.main:app_factory --factory --host 0.0.0.0 --port 8000 --proxy-headers"]
