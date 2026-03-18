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
    Contents API, then fetch each YAML file and parse it.

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
    The project list is fetched once per analysis (not cached globally)
    because it's a single API call and stale data would mislead users.
"""

from __future__ import annotations

import base64
import logging

import httpx
import yaml

from contrib_compass.models import IssueResult, RepoResult, UserProfile
from contrib_compass.sources.github_source import (
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


class UpForGrabsSource:
    """Fetches contribution opportunities from the Up For Grabs project list.

    Up For Grabs is a curated collection of OSS projects that are explicitly
    welcoming to new contributors.  This source fetches their YAML data files
    from GitHub and finds matching open issues.

    Args:
        client: An ``httpx.AsyncClient`` instance (injected for testability).
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

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
        projects = await self._fetch_project_list(token)

        # Filter projects whose tags overlap with user skills
        matched = _filter_by_skills(projects, profile.skills)[:limit]

        repos: list[RepoResult] = []
        for project in matched:
            repo = await self._fetch_repo_for_project(project, token)
            if repo is not None:
                repos.append(repo)

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
        projects = await self._fetch_project_list(token)
        matched = _filter_by_skills(projects, profile.skills)[:_MAX_UFG_PROJECTS]

        all_issues: list[IssueResult] = []
        seen_urls: set[str] = set()

        for project in matched:
            if len(all_issues) >= limit:
                break
            issues = await self._fetch_issues_for_project(project, token)
            for issue in issues:
                if issue.html_url not in seen_urls:
                    seen_urls.add(issue.html_url)
                    all_issues.append(issue)

        logger.info("UpForGrabs returned %d issues", len(all_issues))
        return all_issues[:limit]

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _fetch_project_list(self, token: str) -> list[dict]:
        """Fetch and parse all Up For Grabs project YAML files.

        Returns:
            List of parsed project dicts.
        """
        client = await self._get_client()
        headers = _make_headers(token)

        # Step 1: Get directory listing
        try:
            resp = await client.get(_UFG_CONTENTS_API, headers=headers)
            resp.raise_for_status()
            entries = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Up For Grabs listing: %s", exc)
            return []

        # Step 2: Fetch and parse each YAML file (limit to first 200 for speed)
        projects: list[dict] = []
        for entry in entries[:200]:
            if not entry.get("name", "").endswith(".yml"):
                continue
            try:
                file_resp = await client.get(entry["url"], headers=headers)
                file_resp.raise_for_status()
                file_data = file_resp.json()
                # GitHub returns file content as base64
                content = base64.b64decode(file_data["content"]).decode("utf-8")
                project = yaml.safe_load(content)
                if isinstance(project, dict):
                    projects.append(project)
            except Exception as exc:
                logger.debug("Skipping UFG project file %s: %s", entry.get("name"), exc)

        return projects

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

        client = await self._get_client()
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
        client = await self._get_client()
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

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the injected client or create a temporary one."""
        if self._client is not None:
            return self._client
        # Create a new client — caller is responsible for lifecycle in tests
        return httpx.AsyncClient(timeout=15.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filter_by_skills(projects: list[dict], skills: list[str]) -> list[dict]:
    """Filter and rank projects by tag overlap with user skills.

    Args:
        projects: List of parsed Up For Grabs project dicts.
        skills:   Normalised user skill list.

    Returns:
        Projects sorted by descending tag-overlap count.
    """
    skill_set = set(skills)

    def overlap(project: dict) -> int:
        tags = {t.lower() for t in project.get("tags", [])}
        return len(tags & skill_set)

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
