"""
contrib_compass.config — Application configuration via environment variables.

All settings are read from the process environment (or a .env file loaded by
the caller).  Pydantic-settings validates types and provides defaults so the
app is runnable with minimal configuration.

Required:
    GITHUB_TOKEN  — Personal Access Token for the GitHub API.
                    Without it the app falls back to unauthenticated requests
                    (60 req/hr) and warns the user prominently.

Optional (all have sensible defaults):
    MODEL_NAME                 — sentence-transformers model name
    SENTENCE_TRANSFORMERS_HOME — local cache dir for the downloaded model
    MAX_REPOS                  — max repos returned per analysis
    MAX_ISSUES                 — max issues returned per analysis
    PORT                       — uvicorn listen port
    LOG_LEVEL                  — Python logging level name
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object.  Instantiate once via ``get_settings()``."""

    model_config = SettingsConfigDict(
        # Load .env if present; silently ignore if absent (production uses
        # real env vars injected by Render / Docker).
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GitHub ────────────────────────────────────────────────────────────
    github_token: str = Field(
        default="",
        description=(
            "GitHub Personal Access Token. "
            "Provides 5 000 req/hr vs 60 req/hr unauthenticated. "
            "Create one at https://github.com/settings/tokens"
        ),
    )

    # ── Semantic model ────────────────────────────────────────────────────
    model_name: str = Field(
        default="all-MiniLM-L6-v2",
        description="sentence-transformers model used for semantic re-ranking.",
    )
    sentence_transformers_home: str = Field(
        default=".cache",
        description=(
            "Directory where sentence-transformers caches the downloaded model. "
            "Relative paths are resolved from the working directory."
        ),
    )

    # ── Analysis limits ───────────────────────────────────────────────────
    max_repos: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of repos returned per analysis.",
    )
    max_issues: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of issues returned per analysis.",
    )

    # ── Server ────────────────────────────────────────────────────────────
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="info")

    # ── Derived helpers ───────────────────────────────────────────────────
    @property
    def cache_dir(self) -> Path:
        """Resolved absolute path to the model cache directory."""
        return Path(self.sentence_transformers_home).resolve()

    @property
    def has_github_token(self) -> bool:
        """True when a non-empty GitHub token is configured."""
        return bool(self.github_token)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.lower()


# Module-level singleton — import this everywhere instead of re-instantiating.
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached Settings singleton.

    The first call reads from the environment / .env file.
    Subsequent calls return the cached object (no re-parsing).

    Example:
        >>> from contrib_compass.config import get_settings
        >>> cfg = get_settings()
        >>> cfg.max_repos
        20
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
