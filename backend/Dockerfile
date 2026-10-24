# 開發用：程式碼由 compose watch 同步進來，fastapi dev 自動重新載入
# Python 大版本要與 mise.toml 一致
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# 先只裝依賴，讓 layer cache 在程式碼變動時仍可重用
COPY pyproject.toml uv.lock /app/
COPY backend/pyproject.toml /app/backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package app --no-install-workspace

COPY backend /app/backend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package app

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/backend

CMD ["fastapi", "dev", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
