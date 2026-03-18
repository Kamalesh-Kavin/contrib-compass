"""
contrib_compass.sources.upforgrabs_source — Up For Grabs curated projects adapter.

Responsibility:
    Fetch and parse the Up For Grabs project list, then query GitHub for
    open issues from those projects that match the user's skills.

NOT responsible for:
    - Semantic scoring (see matching/)
    - Repo enrichment (see enrichment/)

Data source:
    Up For Grabs stores project data as individual YAML files in a public
    GitHub repository.  We fetch the directory listing via the GitHub
    Contents API, then fetch each YAML file concurrently and parse it.

    Repo: https://github.com/up-for-grabs/up-for-grabs.net
    Data: /_data/projects/*.yml  (each file is one project)

    Each YAML file has this shape:
        name: "Project Name"
        desc: "Short description"
        site: "https://example.com"
        tags:
          - python
          - web
        upforgrabs:
          link: "https://github.com/owner/repo/issues?q=label%3A..."
          name: "good first issue"
        stats:
          issue-count: 42

Caching:
    The project list is expensive to fetch (200+ sequential requests in the
    original design).  We cache it in-memory at the module level with a
    1-hour TTL so repeated analyses within the same server process don't
    re-fetch everything.  The cache is keyed by the GitHub token used, so
    different tokens get independent caches (different rate-limit buckets).

Concurrency:
    YAML files are fetched concurrently using ``asyncio.gather`` in batches
    of 20 to avoid overwhelming the GitHub Contents API.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx
import yaml

from contrib_compass.models import IssueResult, RepoResult, UserProfile
from contrib_compass.sources.github_source import (
    _CONTRIBUTION_LABELS,
    _parse_repo,
    _resolve_token,
)

logger = logging.getLogger(__name__)

_UFG_CONTENTS_API = (
    "https://api.github.com/repos/up-for-grabs/up-for-grabs.net/contents/_data/projects"
)
_GITHUB_API = "https://api.github.com"

# Maximum number of Up For Grabs projects to inspect per analysis
# (the full list has ~1 000 projects; we take the first N after tag filtering)
_MAX_UFG_PROJECTS = 30

# Maximum number of YAML files to download per analysis — keeps total HTTP
# requests predictable.  Fetching 200 files concurrently in batches of 20
# costs 10 asyncio.gather rounds, which is fast even on a free Render instance.
_MAX_UFG_FILES = 200

# Batch size for concurrent YAML fetches — avoids flooding the API.
_FETCH_BATCH_SIZE = 20

# ---------------------------------------------------------------------------
# Module-level project list cache
# ---------------------------------------------------------------------------
# Structure: { token: {"projects": list[dict], "fetched_at": float} }
# TTL: 3600 seconds (1 hour).  Using the token as cache key ensures different
# users with different auth levels don't share cache entries.
_PROJECT_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 3600


def _get_cached_projects(token: str) -> list[dict] | None:
    """Return cached project list if still fresh, else None."""
    entry = _PROJECT_CACHE.get(token)
    if entry and (time.monotonic() - entry["fetched_at"]) < _CACHE_TTL_SECONDS:
        return entry["projects"]
    return None


def _set_cached_projects(token: str, projects: list[dict]) -> None:
    """Store project list in the in-memory cache."""
    _PROJECT_CACHE[token] = {"projects": projects, "fetched_at": time.monotonic()}


class UpForGrabsSource:
    """Fetches contribution opportunities from the Up For Grabs project list.

    Up For Grabs is a curated collection of OSS projects that are explicitly
    welcoming to new contributors.  This source fetches their YAML data files
    from GitHub and finds matching open issues.

    Args:
        client: An ``httpx.AsyncClient`` instance (injected for testability).
                Must NOT be None in production — always inject a shared client
                from the FastAPI lifespan to avoid resource leaks.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch_repos(
        self,
        profile: UserProfile,
        limit: int = 20,
    ) -> list[RepoResult]:
        """Fetch repos from Up For Grabs that match the user's skills.

        Filters projects by tag overlap with the user's skills.

        Args:
            profile: The user's normalised profile.
            limit:   Max repos to return.

        Returns:
            List of unscored RepoResult objects.
        """
        token = _resolve_token(profile)
        projects = await self._get_project_list(token)

        # Filter projects whose tags overlap with user skills
        matched = _filter_by_skills(projects, profile.skills)[:limit]

        # Fetch GitHub repo metadata for all matched projects concurrently
        tasks = [self._fetch_repo_for_project(p, token) for p in matched]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        repos: list[RepoResult] = []
        for result in results:
            if isinstance(result, RepoResult):
                repos.append(result)
            elif isinstance(result, Exception):
                logger.debug("Repo fetch failed: %s", result)

        logger.info("UpForGrabs returned %d repos", len(repos))
        return repos

    async def fetch_issues(
        self,
        profile: UserProfile,
        limit: int = 50,
    ) -> list[IssueResult]:
        """Fetch open issues from Up For Grabs projects matching user skills.

        Args:
            profile: The user's normalised profile.
            limit:   Max issues to return.

        Returns:
            List of IssueResult objects with difficulty pre-classified.
        """
        token = _resolve_token(profile)
        # Reuse the same cached project list — no second network fetch
        projects = await self._get_project_list(token)
        matched = _filter_by_skills(projects, profile.skills)[:_MAX_UFG_PROJECTS]

        # Fetch issues for all matched projects concurrently
        tasks = [self._fetch_issues_for_project(p, token) for p in matched]
        nested = await asyncio.gather(*tasks, return_exceptions=True)

        all_issues: list[IssueResult] = []
        seen_urls: set[str] = set()

        for result in nested:
            if isinstance(result, Exception):
                logger.debug("Issue fetch failed for a UFG project: %s", result)
                continue
            for issue in result:  # type: ignore[union-attr]
                if len(all_issues) >= limit:
                    break
                if issue.html_url not in seen_urls:
                    seen_urls.add(issue.html_url)
                    all_issues.append(issue)

        logger.info("UpForGrabs returned %d issues", len(all_issues))
        return all_issues[:limit]

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _get_project_list(self, token: str) -> list[dict]:
        """Return the Up For Grabs project list, using the in-memory cache.

        Cache hit:  returns instantly (no HTTP requests).
        Cache miss: fetches the directory listing + all YAML files concurrently,
                    then stores the result in the cache for future calls.

        Args:
            token: GitHub auth token (used as cache key).

        Returns:
            List of parsed project dicts.
        """
        cached = _get_cached_projects(token)
        if cached is not None:
            logger.debug("UpForGrabs project list served from cache (%d projects)", len(cached))
            return cached

        projects = await self._fetch_project_list(token)
        _set_cached_projects(token, projects)
        return projects

    async def _fetch_project_list(self, token: str) -> list[dict]:
        """Fetch and parse all Up For Grabs project YAML files.

        Fetches YAML files concurrently in batches of ``_FETCH_BATCH_SIZE``
        to avoid overwhelming the GitHub Contents API while still being much
        faster than the previous sequential approach (200 requests → ~10 rounds).

        Returns:
            List of parsed project dicts.
        """
        client = self._get_client()
        headers = _make_headers(token)

        # Step 1: Get directory listing (one request)
        try:
            resp = await client.get(_UFG_CONTENTS_API, headers=headers)
            resp.raise_for_status()
            entries = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Up For Grabs listing: %s", exc)
            return []

        # Collect YAML file entries (up to _MAX_UFG_FILES)
        yaml_entries = [e for e in entries if e.get("name", "").endswith(".yml")][:_MAX_UFG_FILES]

        # Step 2: Fetch YAML files concurrently in batches
        projects: list[dict] = []
        for batch_start in range(0, len(yaml_entries), _FETCH_BATCH_SIZE):
            batch = yaml_entries[batch_start : batch_start + _FETCH_BATCH_SIZE]
            tasks = [self._fetch_single_yaml(entry, headers, client) for entry in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    projects.append(result)
                # Exceptions are silently skipped (logged inside _fetch_single_yaml)

        logger.info("UpForGrabs fetched %d projects from YAML files", len(projects))
        return projects

    async def _fetch_single_yaml(
        self,
        entry: dict,
        headers: dict[str, str],
        client: httpx.AsyncClient,
    ) -> dict | None:
        """Fetch and parse one YAML project file from GitHub Contents API.

        Args:
            entry:   Directory entry dict from the GitHub Contents API.
            headers: HTTP headers (auth + accept).
            client:  The shared async HTTP client.

        Returns:
            Parsed project dict, or None on any error.
        """
        try:
            file_resp = await client.get(entry["url"], headers=headers)
            file_resp.raise_for_status()
            file_data = file_resp.json()
            # GitHub returns file content as base64-encoded bytes
            content = base64.b64decode(file_data["content"]).decode("utf-8")
            project = yaml.safe_load(content)
            return project if isinstance(project, dict) else None
        except Exception as exc:
            logger.debug("Skipping UFG project file %s: %s", entry.get("name"), exc)
            return None

    async def _fetch_repo_for_project(
        self,
        project: dict,
        token: str,
    ) -> RepoResult | None:
        """Fetch GitHub repo metadata for an Up For Grabs project.

        Extracts the owner/repo from the upforgrabs.link URL and queries
        the GitHub Repos API.

        Args:
            project: Parsed YAML dict for one Up For Grabs project.
            token:   GitHub auth token.

        Returns:
            RepoResult or None if the repo cannot be resolved.
        """
        owner_repo = _extract_owner_repo(project)
        if not owner_repo:
            return None

        client = self._get_client()
        headers = _make_headers(token)

        try:
            resp = await client.get(
                f"{_GITHUB_API}/repos/{owner_repo}",
                headers=headers,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return _parse_repo(resp.json())
        except httpx.HTTPError as exc:
            logger.debug("Cannot fetch repo %s: %s", owner_repo, exc)
            return None

    async def _fetch_issues_for_project(
        self,
        project: dict,
        token: str,
    ) -> list[IssueResult]:
        """Fetch open issues for a single Up For Grabs project.

        Uses the label stored in the project's ``upforgrabs.name`` field
        (usually "good first issue" or similar).

        Args:
            project: Parsed YAML dict for one Up For Grabs project.
            token:   GitHub auth token.

        Returns:
            List of IssueResult objects.
        """
        owner_repo = _extract_owner_repo(project)
        if not owner_repo:
            return []

        label = project.get("upforgrabs", {}).get("name", "good first issue")
        client = self._get_client()
        headers = _make_headers(token)

        try:
            resp = await client.get(
                f"{_GITHUB_API}/repos/{owner_repo}/issues",
                params={"labels": label, "state": "open", "per_page": 10},
                headers=headers,
            )
            if resp.status_code in {404, 410}:
                return []
            resp.raise_for_status()
            items = resp.json()
        except httpx.HTTPError as exc:
            logger.debug("Cannot fetch issues for %s: %s", owner_repo, exc)
            return []

        results: list[IssueResult] = []
        for item in items:
            # Repo issues API doesn't include repository_url in the same format
            item.setdefault("repository_url", f"{_GITHUB_API}/repos/{owner_repo}")
            from contrib_compass.sources.github_source import _parse_issue

            issue = _parse_issue(item)
            if issue:
                results.append(issue)

        return results

    def _get_client(self) -> httpx.AsyncClient:
        """Return the injected client.

        Raises:
            RuntimeError: If no client was injected.  Always inject a shared
                ``httpx.AsyncClient`` from the FastAPI lifespan context instead
                of letting this class create its own — that avoids resource
                leaks (unclosed client connections).
        """
        if self._client is None:
            # Fallback for tests / standalone use — callers should prefer injecting.
            # We create a temporary client here; the caller must ensure it is closed.
            logger.warning(
                "UpForGrabsSource created a temporary httpx.AsyncClient.  "
                "Inject a shared client for production use."
            )
            return httpx.AsyncClient(timeout=20.0)
        return self._client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filter_by_skills(projects: list[dict], skills: list[str]) -> list[dict]:
    """Filter and rank projects by tag overlap with user skills.

    Tag matching uses a two-pass approach:
    1. Exact match: normalised tag == normalised skill.
    2. Substring match: e.g. skill "amazon web services" won't match tag "aws",
       but skill "aws" WILL match tag "aws" in pass 1.
       To bridge common abbreviations, we also check if any skill is a substring
       of a tag or vice versa (only for tokens ≥ 3 chars to avoid noise).

    Args:
        projects: List of parsed Up For Grabs project dicts.
        skills:   Normalised user skill list.

    Returns:
        Projects sorted by descending tag-overlap count.
    """
    skill_set = set(skills)

    def overlap(project: dict) -> int:
        tags = {t.lower() for t in project.get("tags", [])}
        # Exact overlap
        exact = len(tags & skill_set)
        # Substring overlap: tag contains a skill token or skill contains a tag
        substring_bonus = 0
        for skill in skill_set:
            if skill in tags:
                continue  # already counted in exact
            for tag in tags:
                if len(skill) >= 3 and len(tag) >= 3 and (skill in tag or tag in skill):
                    substring_bonus += 1
                    break
        return exact + substring_bonus

    scored = [(overlap(p), p) for p in projects if overlap(p) > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


def _extract_owner_repo(project: dict) -> str | None:
    """Extract 'owner/repo' from a project's upforgrabs.link URL.

    The link typically looks like:
        https://github.com/owner/repo/issues?q=...

    Args:
        project: Parsed YAML dict for one Up For Grabs project.

    Returns:
        "owner/repo" string, or None if the URL cannot be parsed.
    """
    link: str = project.get("upforgrabs", {}).get("link", "")
    if "github.com/" not in link:
        return None
    # Strip query string, split on github.com/
    path = link.split("github.com/", 1)[-1].split("?")[0].split("#")[0]
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None


def _make_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
