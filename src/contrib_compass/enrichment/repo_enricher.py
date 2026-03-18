"""
contrib_compass.enrichment.repo_enricher — Generate contribution tips for repos.

Responsibility:
    For each of the top-N repos, make one additional GitHub API call to
    check for contribution-friendliness signals, then generate human-readable
    tip badges shown in the repo card UI.

NOT responsible for:
    - Scoring / ranking (see matching/)
    - Fetching the repo list itself (see sources/)

Signals checked per repo (all from a single ``GET /repos/{owner}/{repo}``
call that we may already have, plus a check for CONTRIBUTING.md):

    1. CONTRIBUTING.md exists at root → "Has contribution guide"
    2. Last push age → "Active — pushed N days ago" or "Inactive"
    3. Open issues count → "N open issues"
    4. Is archived → warning badge
    5. Has a Code of Conduct → "Has Code of Conduct"

We limit enrichment to the top 10 repos to avoid burning API rate limit.
"""

from __future__ import annotations

import logging

import httpx

from contrib_compass.models import ContributionTip, RepoResult

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_ENRICH_LIMIT = 10   # only enrich top N repos


async def enrich_repos(
    repos: list[RepoResult],
    token: str,
    client: httpx.AsyncClient | None = None,
) -> list[RepoResult]:
    """Enrich the top repos with contribution tips.

    Makes one additional GitHub API call per repo (to check for
    CONTRIBUTING.md) and generates tip badges from the existing repo data.

    Args:
        repos:  Ranked list of repos (already scored).
        token:  GitHub auth token for API calls.
        client: Optional injected httpx client (for testing).

    Returns:
        List of RepoResult objects with ``tips`` populated for the top N.
        Repos beyond position N are returned unchanged.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        enriched: list[RepoResult] = []
        for i, repo in enumerate(repos):
            if i < _ENRICH_LIMIT:
                tips = await _build_tips(repo, token, client)
                enriched.append(RepoResult(**{**repo.model_dump(), "tips": tips}))
            else:
                enriched.append(repo)
        return enriched
    finally:
        if owns_client and client:
            await client.aclose()


async def _build_tips(
    repo: RepoResult,
    token: str,
    client: httpx.AsyncClient,
) -> list[ContributionTip]:
    """Build contribution tips for a single repo.

    Args:
        repo:   The repo to enrich.
        token:  GitHub auth token.
        client: httpx client.

    Returns:
        List of ContributionTip objects.
    """
    tips: list[ContributionTip] = []
    headers = _make_headers(token)

    # ── Tip 1: CONTRIBUTING.md ──────────────────────────────────────────
    has_contributing = await _check_file_exists(
        repo.full_name, "CONTRIBUTING.md", headers, client
    )
    if has_contributing:
        tips.append(ContributionTip(
            icon="📖",
            message="Has CONTRIBUTING.md",
            positive=True,
        ))
    else:
        tips.append(ContributionTip(
            icon="⚠️",
            message="No CONTRIBUTING.md",
            positive=False,
        ))

    # ── Tip 2: Activity (from last_pushed_at on the repo) ───────────────
    days_ago = repo.last_pushed_days_ago
    if days_ago is not None:
        if days_ago <= 7:
            tips.append(ContributionTip(
                icon="🔥",
                message=f"Very active — pushed {days_ago}d ago",
                positive=True,
            ))
        elif days_ago <= 30:
            tips.append(ContributionTip(
                icon="✅",
                message=f"Active — pushed {days_ago}d ago",
                positive=True,
            ))
        elif days_ago <= 180:
            tips.append(ContributionTip(
                icon="🕐",
                message=f"Last push {days_ago}d ago",
                positive=True,
            ))
        else:
            tips.append(ContributionTip(
                icon="🐢",
                message=f"Slow — last push {days_ago}d ago",
                positive=False,
            ))

    # ── Tip 3: Open issues count ─────────────────────────────────────────
    if repo.open_issues > 0:
        tips.append(ContributionTip(
            icon="🐛",
            message=f"{repo.open_issues:,} open issues",
            positive=True,
        ))

    # ── Tip 4: Archived ──────────────────────────────────────────────────
    # (archived flag is not in RepoResult currently — handled by filtering
    #  it out in github_source before it reaches enrichment)

    # ── Tip 5: Code of Conduct ───────────────────────────────────────────
    has_coc = await _check_file_exists(
        repo.full_name, "CODE_OF_CONDUCT.md", headers, client
    )
    if has_coc:
        tips.append(ContributionTip(
            icon="🤝",
            message="Has Code of Conduct",
            positive=True,
        ))

    return tips


async def _check_file_exists(
    full_name: str,
    filename: str,
    headers: dict[str, str],
    client: httpx.AsyncClient,
) -> bool:
    """Check whether a file exists at the root of a GitHub repo.

    Uses ``HEAD /repos/{owner}/{repo}/contents/{filename}`` to avoid
    downloading the file content.

    Args:
        full_name: "owner/repo" string.
        filename:  File name to check (e.g. "CONTRIBUTING.md").
        headers:   GitHub API request headers.
        client:    httpx client.

    Returns:
        True if the file exists (HTTP 200), False otherwise.
    """
    url = f"{_GITHUB_API}/repos/{full_name}/contents/{filename}"
    try:
        resp = await client.head(url, headers=headers)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _make_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
