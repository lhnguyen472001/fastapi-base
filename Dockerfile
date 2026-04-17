# syntax=docker/dockerfile:1.7
# ============================================================================
# Stage 1 — builder: install build toolchain + project dependencies into .venv
# ============================================================================
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Build deps for any wheels that need compilation (bcrypt, cffi, cryptography).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv pinned for reproducible builds.
RUN pip install --no-cache-dir uv==0.5.11

WORKDIR /app

# Cache layer: install dependencies first, without the project source.
# README.md is required because pyproject.toml declares ``readme = "README.md"``
# and hatchling validates the file at build time.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the source and install the project itself.
# README.md is required because pyproject.toml has ``readme = "README.md"``
# and hatchling validates it exists at build time.
COPY README.md ./
COPY apps ./apps
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# ============================================================================
# Stage 2 — runtime: minimal image with only the venv + source
# ============================================================================
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Runtime-only OS deps (no compilers, no headers).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home /app --shell /bin/false app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/apps /app/apps
COPY --from=builder --chown=app:app /app/alembic /app/alembic
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "apps.factory:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
