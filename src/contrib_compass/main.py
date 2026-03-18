"""
contrib_compass.main — FastAPI application factory and entry point.

This module creates the FastAPI app, registers the startup/shutdown lifespan
(which pre-loads the sentence-transformers model into app.state so every
request reuses the same in-memory model), and mounts the web router.

What this module does:
    - Creates the FastAPI app with a title, description, and version.
    - Loads the sentence-transformers model on startup and stores it on
      ``app.state.model``. Router handlers access it via ``request.app.state.model``.
    - Provides a ``GET /health`` endpoint that CI / load-balancers can poll.
    - Configures structured JSON logging at the level set in Settings.

What this module does NOT do:
    - Define routes (see web/router.py)
    - Handle sessions (see web/session.py)
    - Score or rank results (see matching/)

Entry point (local dev):
    uvicorn contrib_compass.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from contrib_compass.config import get_settings

# Set the model cache directory BEFORE importing sentence_transformers so the
# library respects our custom cache location on every code path.
_settings = get_settings()
os.environ.setdefault(
    "SENTENCE_TRANSFORMERS_HOME",
    str(_settings.cache_dir),
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — model pre-load
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager.

    Runs on startup:
        1. Configures logging.
        2. Pre-loads the sentence-transformers model so the first real request
           is not penalised by a 10-30s model download/load.

    Runs on shutdown:
        - Currently a no-op (in-memory state is discarded automatically).

    The loaded model is stored on ``app.state.model``.
    If loading fails (e.g. on Render free tier with <512 MB RAM), the app
    continues with ``app.state.model = None`` and falls back to keyword-only
    scoring with a warning logged.
    """
    # ── Configure logging ──────────────────────────────────────────────────
    logging.basicConfig(
        level=_settings.log_level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    # ── Pre-load sentence-transformers model ───────────────────────────────
    logger.info(
        "Loading sentence-transformers model '%s' from cache '%s'…",
        _settings.model_name,
        _settings.cache_dir,
    )
    try:
        # Import is intentionally deferred here so the module can be imported
        # without triggering a model download (useful in tests).
        from sentence_transformers import SentenceTransformer  # type: ignore[import]

        model = SentenceTransformer(
            _settings.model_name,
            cache_folder=str(_settings.cache_dir),
        )
        app.state.model = model
        logger.info("Model loaded successfully.")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load sentence-transformers model: %s. "
            "Falling back to keyword-only scoring.",
            exc,
        )
        app.state.model = None

    yield  # ← app is live here

    # ── Shutdown ───────────────────────────────────────────────────────────
    logger.info("Shutting down contrib-compass.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Called once at import time to produce the ``app`` module-level object
    that uvicorn picks up.

    Returns:
        Configured FastAPI instance.
    """
    settings = get_settings()

    application = FastAPI(
        title="ContribCompass",
        description=(
            "Find open source contribution opportunities matched to your skills. "
            "Upload your resume or enter your stack — ContribCompass ranks GitHub "
            "repos and issues using semantic search."
        ),
        version="0.1.0",
        # Only expose /docs in non-production (you can gate this on an env var)
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    # ── Mount web router ───────────────────────────────────────────────────
    # Import here to avoid circular imports at module load time.
    from contrib_compass.web.router import router  # noqa: PLC0415

    application.include_router(router)

    logger.debug("FastAPI app created (max_repos=%d, max_issues=%d)", settings.max_repos, settings.max_issues)
    return application


# Module-level app instance — uvicorn uses this.
app: FastAPI = create_app()
