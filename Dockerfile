# ── Stage 1: dependency builder ────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Copy uv binary — the only build tool needed
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install production deps into an isolated venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: lean runtime image ────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy only the venv — no uv, no pip, no build tools in production
COPY --from=builder /build/.venv /app/.venv

# Copy application and migration code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

RUN chmod +x docker-entrypoint.sh

# Activate venv for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
