"""
contrib_compass.sources.github_source — GitHub Search API adapter.

Responsibility:
    Query the GitHub Search API to find:
    - Repositories matching the user's programming languages and skills
    - Issues labeled "good first issue" or "help wanted" in active repos

NOT responsible for:
    - Semantic scoring (see matching/)
    - Repo enrichment tips (see enrichment/)

Rate limiting:
    GitHub Search API allows 30 requests/min (authenticated) or 10/min
    (unauthenticated).  This module checks ``X-RateLimit-Remaining`` on
    every response and raises ``RateLimitError`` when the limit is exhausted.

Authentication:
    Reads the token from ``profile.github_token`` (user-provided in the UI)
    or falls back to ``settings.github_token`` (server-side env var).
    Without a token, the unauthenticated limit of 60 req/hr applies.

API docs:
    https://docs.github.com/en/rest/search/search
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from contrib_compass.config import get_settings
from contrib_compass.difficulty.classifier import classify_issue
from contrib_compass.models import IssueResult, RepoResult, UserProfile

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_SEARCH_REPOS = f"{_GITHUB_API}/search/repositories"
_SEARCH_ISSUES = f"{_GITHUB_API}/search/issues"

# Minimum repo age filter — exclude repos with no push in the last 12 months
_MIN_PUSHED = "2025-01-01"

# Issue labels we search for
_CONTRIBUTION_LABELS = ["good first issue", "help wanted"]


class RateLimitError(RuntimeError):
    """Raised when the GitHub API rate limit is exhausted."""


class GitHubSource:
    """Fetches repos and issues from the GitHub Search API.

    Args:
        client: An ``httpx.AsyncClient`` instance (injected for testability).
                If None, a new client is created per request (not recommended
                for production — use dependency injection via FastAPI).
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    # ── Public API ─────────────────────────────────────────────────────────

    async def fetch_repos(
        self,
        profile: UserProfile,
        limit: int = 20,
    ) -> list[RepoResult]:
        """Search GitHub for repos matching the user's languages and skills.

        Builds a search query from the user's language list and top skills,
        filtering to recently active, non-archived repos.

        Args:
            profile: The user's normalised profile.
            limit:   Max repos to return (capped at 100 by GitHub).

        Returns:
            List of RepoResult objects (unscored).

        Raises:
            RateLimitError: If GitHub API rate limit is hit.
        """
        query = _build_repo_query(profile)
        logger.debug("GitHub repo query: %s", query)

        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(limit, 100),
        }

        data = await self._get(_SEARCH_REPOS, params=params, token=_resolve_token(profile))
        items = data.get("items", [])

        repos: list[RepoResult] = []
        for item in items:
            repo = _parse_repo(item)
            if repo is not None:
                repos.append(repo)

        logger.info("GitHub returned %d repos", len(repos))
        return repos

    async def fetch_issues(
        self,
        profile: UserProfile,
        limit: int = 50,
    ) -> list[IssueResult]:
        """Search GitHub for open contribution-friendly issues.

        Searches for issues labeled "good first issue" OR "help wanted" in
        repos that use the user's primary languages.

        Args:
            profile: The user's normalised profile.
            limit:   Max issues to return (per label query).

        Returns:
            List of IssueResult objects with difficulty pre-classified.

        Raises:
            RateLimitError: If GitHub API rate limit is hit.
        """
        token = _resolve_token(profile)
        per_label = max(limit // len(_CONTRIBUTION_LABELS), 10)

        all_issues: list[IssueResult] = []
        seen_urls: set[str] = set()

        for label in _CONTRIBUTION_LABELS:
            query = _build_issue_query(profile, label)
            logger.debug("GitHub issue query [%s]: %s", label, query)

            params = {
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": min(per_label, 100),
            }

            data = await self._get(_SEARCH_ISSUES, params=params, token=token)
            items = data.get("items", [])

            for item in items:
                issue = _parse_issue(item)
                if issue is not None and issue.html_url not in seen_urls:
                    seen_urls.add(issue.html_url)
                    all_issues.append(issue)

        logger.info("GitHub returned %d issues total", len(all_issues))
        return all_issues[:limit]

    # ── Internal HTTP helper ───────────────────────────────────────────────

    async def _get(
        self,
        url: str,
        params: dict[str, str | int],
        token: str,
    ) -> dict:
        """Make an authenticated GET request and return the parsed JSON body.

        If the token produces a 401 Unauthorized response (expired / revoked),
        the request is automatically retried without any Authorization header so
        that at least the unauthenticated rate-limit tier is used instead of
        failing completely.

        Args:
            url:    Full API URL.
            params: Query parameters dict.
            token:  GitHub token (empty string for unauthenticated).

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            RateLimitError: If ``X-RateLimit-Remaining`` is 0.
            httpx.HTTPStatusError: On 4xx/5xx responses (other than 401 with
                a token, which triggers an unauthenticated retry).
        """
        base_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            # --- First attempt (with token if available) -------------------
            headers = dict(base_headers)
            if token:
                headers["Authorization"] = f"Bearer {token}"

            response = await client.get(url, params=params, headers=headers)

            # If the token is invalid/expired, retry without it so the
            # unauthenticated rate-limit (60 req/hr) is used as a fallback
            # rather than surfacing a confusing 401 error to the user.
            if response.status_code == 401 and token:
                logger.warning(
                    "GitHub token returned 401 — token may be expired or "
                    "revoked. Retrying without Authorization header."
                )
                response = await client.get(url, params=params, headers=base_headers)

            # Check rate limit before raising on status
            remaining = int(response.headers.get("X-RateLimit-Remaining", "1"))
            if remaining == 0:
                reset_ts = int(response.headers.get("X-RateLimit-Reset", "0"))
                raise RateLimitError(
                    f"GitHub API rate limit exhausted. Resets at epoch {reset_ts}. "
                    "Provide a GitHub token for 5 000 req/hr."
                )

            response.raise_for_status()
            return response.json()

        finally:
            if self._owns_client and client is not self._client:
                await client.aclose()


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------


def _build_repo_query(profile: UserProfile) -> str:
    """Build a GitHub repository search query from a user profile.

    Strategy:
    - Include language: qualifiers for each of the user's languages (OR'd
      together by sending multiple language qualifiers isn't supported, so
      we use the primary language only).
    - Add topic: qualifiers for skill-matching (e.g. "topic:fastapi").
    - Exclude archived repos and filter for recently active ones.

    Args:
        profile: Normalised user profile.

    Returns:
        Query string for the GitHub Search Repositories API.
    """
    parts: list[str] = []

    # Primary language filter (GitHub supports one language: qualifier per query)
    if profile.languages:
        parts.append(f"language:{profile.languages[0]}")

    # Add topic qualifiers for top skills (max 3 to avoid over-constraining)
    topic_skills = [s for s in profile.skills if len(s) > 3][:3]
    for skill in topic_skills:
        # Only include single-word skills as topics (multi-word don't work as topics)
        if " " not in skill:
            parts.append(f"topic:{skill}")

    # Quality filters
    parts.append(f"pushed:>{_MIN_PUSHED}")
    parts.append("archived:false")
    parts.append("stars:>10")  # avoid abandoned/empty repos

    return " ".join(parts)


def _build_issue_query(profile: UserProfile, label: str) -> str:
    """Build a GitHub issue search query for a specific contribution label.

    Args:
        profile: Normalised user profile.
        label:   Issue label to search for (e.g. "good first issue").

    Returns:
        Query string for the GitHub Search Issues API.
    """
    parts: list[str] = [
        "type:issue",
        "state:open",
        f'label:"{label}"',
    ]

    # Filter by primary language if available
    if profile.languages:
        parts.append(f"language:{profile.languages[0]}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------


def _parse_repo(item: dict) -> RepoResult | None:
    """Parse a single GitHub Search API repository item into a RepoResult.

    Args:
        item: Raw dict from GitHub's ``/search/repositories`` response.

    Returns:
        RepoResult, or None if required fields are missing.
    """
    try:
        pushed_at_str = item.get("pushed_at")
        pushed_at: datetime | None = None
        if pushed_at_str:
            pushed_at = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))

        return RepoResult(
            full_name=item["full_name"],
            html_url=item["html_url"],
            description=item.get("description"),
            language=item.get("language"),
            topics=item.get("topics", []),
            stars=item.get("stargazers_count", 0),
            forks=item.get("forks_count", 0),
            open_issues=item.get("open_issues_count", 0),
            last_pushed_at=pushed_at,
        )
    except (KeyError, ValueError) as exc:
        logger.warning("Skipping malformed repo item: %s", exc)
        return None


def _parse_issue(item: dict) -> IssueResult | None:
    """Parse a single GitHub Search API issue item into an IssueResult.

    Args:
        item: Raw dict from GitHub's ``/search/issues`` response.

    Returns:
        IssueResult with difficulty pre-classified, or None on parse error.
    """
    try:
        labels = [lb["name"] for lb in item.get("labels", [])]

        repo_url = item.get("repository_url", "")
        # Convert API URL to HTML URL: api.github.com/repos/owner/repo → github.com/owner/repo
        repo_full_name = "/".join(repo_url.split("/")[-2:]) if repo_url else "unknown/unknown"
        repo_html_url = f"https://github.com/{repo_full_name}"

        created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))

        body = item.get("body") or ""
        body_preview = body[:300] if body else None

        # Classify difficulty before construction (heuristic, no extra API call)
        difficulty, reason = classify_issue(
            labels=labels,
            comment_count=item.get("comments", 0),
            created_at=created_at,
            repo_stars=None,  # not available in search results; enriched later if needed
        )

        return IssueResult(
            number=item["number"],
            title=item["title"],
            html_url=item["html_url"],
            repo_full_name=repo_full_name,
            repo_html_url=repo_html_url,
            labels=labels,
            comment_count=item.get("comments", 0),
            created_at=created_at,
            updated_at=updated_at,
            difficulty=difficulty,
            difficulty_reason=reason,
            body_preview=body_preview,
        )
    except (KeyError, ValueError) as exc:
        logger.warning("Skipping malformed issue item: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def _resolve_token(profile: UserProfile) -> str:
    """Return the best available GitHub token.

    Preference order:
    1. Token provided by the user in the web form (most privileged, per-user)
    2. Server-side token from environment / settings (shared, fallback)
    3. Empty string (unauthenticated, very limited)

    Args:
        profile: UserProfile which may carry a github_token.

    Returns:
        Token string, or "" if none is available.
    """
    if profile.github_token:
        return profile.github_token
    settings = get_settings()
    return settings.github_token
