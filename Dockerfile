# ---------------------------------------------------------------------------
# Dockerfile for contrib-compass
#
# Multi-stage build:
#   Stage 1 (builder) — install Python deps with uv into an isolated venv
#   Stage 2 (runtime) — copy only the venv + source, run as non-root user
#
# Build:  docker build -t contrib-compass .
# Run:    docker run -p 8000:8000 --env-file .env contrib-compass
# ---------------------------------------------------------------------------

# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv — fast Python package installer
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml .

# Create a venv and install all production dependencies
# UV_COMPILE_BYTECODE=1 pre-compiles .pyc files for faster startup
RUN uv venv .venv && \
    UV_COMPILE_BYTECODE=1 uv pip install --python .venv/bin/python \
        --no-cache ".[dev]"

# Copy source after deps to preserve cache on code-only changes
COPY src/ src/

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Create a non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy the venv and source from builder
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/src src/

# Copy the model cache directory (empty on fresh build; populated at runtime)
COPY .cache/ .cache/

# Ensure .cache is writable for model download on first run
RUN chown -R appuser:appgroup /app

USER appuser

# Set SENTENCE_TRANSFORMERS_HOME so the model is cached inside the container
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Graceful shutdown with --timeout-graceful-shutdown
CMD ["uvicorn", "contrib_compass.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]
