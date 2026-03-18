"""
contrib_compass.web.session — In-memory async session store.

Responsibility:
    Provide a lightweight dict-backed store that maps a UUID session_id to an
    AnalysisResult (or a sentinel string while the background task is still
    running).  The store is intentionally simple — no persistence, no
    expiration — appropriate for a stateless single-process deployment.

NOT responsible for:
    - HTTP session cookies (we use path-based IDs, not cookies)
    - Persistence / database (there is no DB in this project)

Concurrency:
    All mutations are guarded by a single asyncio.Lock to prevent races
    between the background task writer and the polling reader.

Eviction:
    Sessions older than SESSION_TTL_SECONDS are pruned lazily on each
    ``set`` call to prevent unbounded memory growth in long-running processes.

Public API:
    session_store.set(session_id, result)
    session_store.get(session_id) → AnalysisResult | None
    session_store.set_status(session_id, status)
    session_store.new_session() → str (UUID)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from contrib_compass.models import AnalysisResult, AnalysisStatus

logger = logging.getLogger(__name__)

# Sessions older than this are pruned to prevent unbounded growth.
SESSION_TTL_SECONDS: int = 60 * 60  # 1 hour


class SessionStore:
    """Thread-safe (asyncio) in-memory store for analysis sessions.

    Usage:
        from contrib_compass.web.session import session_store

        # Create a new session
        session_id = session_store.new_session()

        # Store the finished result
        await session_store.set(session_id, result)

        # Poll for completion
        result = await session_store.get(session_id)
    """

    def __init__(self) -> None:
        # Maps session_id → AnalysisResult
        self._store: dict[str, AnalysisResult] = {}
        # Maps session_id → creation UTC datetime (for TTL pruning)
        self._created_at: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def new_session(self) -> str:
        """Generate a new unique session ID (UUID4) and register it as PENDING.

        This is synchronous because it is called before the background task
        starts and must return immediately in the POST /analyze handler.

        Returns:
            A fresh UUID4 string (e.g. "a1b2c3d4-...").
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)
        # Create a minimal placeholder result so get() never returns None for
        # a freshly created session.
        placeholder = AnalysisResult(
            session_id=session_id,
            status=AnalysisStatus.PENDING,
            created_at=now,
        )
        self._store[session_id] = placeholder
        self._created_at[session_id] = now
        logger.debug("New session created: %s", session_id)
        return session_id

    async def get(self, session_id: str) -> Optional[AnalysisResult]:
        """Return the AnalysisResult for a session, or None if not found.

        Args:
            session_id: The UUID returned by new_session().

        Returns:
            The stored AnalysisResult, or None if the session doesn't exist.
        """
        async with self._lock:
            return self._store.get(session_id)

    async def set(self, session_id: str, result: AnalysisResult) -> None:
        """Store a completed (or error) AnalysisResult for a session.

        Also triggers lazy eviction of expired sessions.

        Args:
            session_id: The target session UUID.
            result:     The AnalysisResult to store.
        """
        async with self._lock:
            self._store[session_id] = result
            self._created_at.setdefault(session_id, datetime.now(tz=timezone.utc))
            self._evict_expired()

    async def set_running(self, session_id: str) -> None:
        """Mark a session as RUNNING (background task has started).

        Args:
            session_id: The target session UUID.
        """
        async with self._lock:
            existing = self._store.get(session_id)
            if existing is not None:
                self._store[session_id] = AnalysisResult(
                    **{**existing.model_dump(), "status": AnalysisStatus.RUNNING}
                )

    # ── Private helpers ────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        """Remove sessions older than SESSION_TTL_SECONDS.

        Must be called while the lock is already held.
        """
        now = datetime.now(tz=timezone.utc)
        expired = [
            sid
            for sid, created in self._created_at.items()
            if (now - created).total_seconds() > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            self._store.pop(sid, None)
            self._created_at.pop(sid, None)
            logger.debug("Evicted expired session: %s", sid)


# Module-level singleton — import this in router.py and background tasks.
session_store = SessionStore()
