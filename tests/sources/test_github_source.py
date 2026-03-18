"""
tests/sources/test_github_source.py — Unit tests for GitHubSource.

Uses respx to mock httpx calls so no real network requests are made.

Tests cover:
  - fetch_repos: parses API response into RepoResult list
  - fetch_issues: parses API response into IssueResult list
  - fetch_repos: handles RateLimitError when X-RateLimit-Remaining == 0
  - _parse_repo: skips malformed items gracefully
  - _get: retries without Authorization header when token returns 401
"""

from __future__ import annotations

import pytest
import respx
from httpx import AsyncClient, Response

from contrib_compass.models import UserProfile
from contrib_compass.sources.github_source import GitHubSource, RateLimitError


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(
        role="Backend Engineer",
        skills=["python", "fastapi"],
        languages=["python"],
        github_token="fake-token",
    )


_REPO_ITEM = {
    "full_name": "tiangolo/fastapi",
    "html_url": "https://github.com/tiangolo/fastapi",
    "description": "FastAPI framework",
    "language": "Python",
    "topics": ["fastapi", "python"],
    "stargazers_count": 75000,
    "forks_count": 6000,
    "open_issues_count": 200,
    "pushed_at": "2026-02-01T00:00:00Z",
}

_ISSUE_ITEM = {
    "number": 42,
    "title": "Add Python async docs",
    "html_url": "https://github.com/tiangolo/fastapi/issues/42",
    "repository_url": "https://api.github.com/repos/tiangolo/fastapi",
    "labels": [{"name": "good first issue"}],
    "comments": 2,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-02-01T00:00:00Z",
    "body": "We should add async docs.",
    "state": "open",
}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repos_returns_repo_results(profile):
    """fetch_repos should parse GitHub API response into RepoResult objects."""
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=Response(
            200,
            json={"items": [_REPO_ITEM]},
            headers={"X-RateLimit-Remaining": "30"},
        )
    )

    async with AsyncClient() as client:
        source = GitHubSource(client=client)
        repos = await source.fetch_repos(profile, limit=5)

    assert len(repos) == 1
    assert repos[0].full_name == "tiangolo/fastapi"
    assert repos[0].language == "Python"
    assert repos[0].stars == 75000


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repos_rate_limit_raises(profile):
    """When X-RateLimit-Remaining is 0, RateLimitError should be raised."""
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
        )
    )

    async with AsyncClient() as client:
        source = GitHubSource(client=client)
        with pytest.raises(RateLimitError):
            await source.fetch_repos(profile, limit=5)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_issues_returns_issue_results(profile):
    """fetch_issues should parse GitHub API response into IssueResult objects."""
    # Responds to both "good first issue" and "help wanted" searches
    respx.get("https://api.github.com/search/issues").mock(
        return_value=Response(
            200,
            json={"items": [_ISSUE_ITEM]},
            headers={"X-RateLimit-Remaining": "30"},
        )
    )

    async with AsyncClient() as client:
        source = GitHubSource(client=client)
        issues = await source.fetch_issues(profile, limit=10)

    # At least one issue returned (may be de-duped if both label searches return same item)
    assert len(issues) >= 1
    assert issues[0].number == 42
    assert issues[0].repo_full_name == "tiangolo/fastapi"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repos_empty_response(profile):
    """An empty items list should return an empty repo list."""
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=Response(
            200,
            json={"items": []},
            headers={"X-RateLimit-Remaining": "30"},
        )
    )

    async with AsyncClient() as client:
        source = GitHubSource(client=client)
        repos = await source.fetch_repos(profile, limit=5)

    assert repos == []


@pytest.mark.asyncio
@respx.mock
async def test_get_retries_without_token_on_401():
    """When a token produces a 401, _get should retry unauthenticated and succeed."""
    # Profile WITH a token that the server rejects
    bad_token_profile = UserProfile(
        role="Engineer",
        skills=["python"],
        languages=["python"],
        github_token="expired-token",
    )

    call_count = 0

    def side_effect(request, route):
        nonlocal call_count
        call_count += 1
        # First call (with Authorization header) → 401
        if "Authorization" in request.headers:
            return Response(401, json={"message": "Bad credentials"})
        # Second call (without Authorization) → 200
        return Response(
            200,
            json={"items": [_REPO_ITEM]},
            headers={"X-RateLimit-Remaining": "10"},
        )

    respx.get("https://api.github.com/search/repositories").mock(side_effect=side_effect)

    async with AsyncClient() as client:
        source = GitHubSource(client=client)
        repos = await source.fetch_repos(bad_token_profile, limit=5)

    # Should have retried and succeeded
    assert call_count == 2
    assert len(repos) == 1
    assert repos[0].full_name == "tiangolo/fastapi"
