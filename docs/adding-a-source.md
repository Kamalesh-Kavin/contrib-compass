# Adding a new data source

This guide walks through implementing and registering a new issue/repo source in ContribCompass.

The existing sources (`github_source.py` and `upforgrabs_source.py`) are good reference implementations.

---

## 1. Understand the base contract

Every source must implement `BaseSource` from `src/contrib_compass/sources/base.py`:

```python
from abc import ABC, abstractmethod
from contrib_compass.models import IssueResult, RepoResult, UserProfile

class BaseSource(ABC):
    """Abstract base class for contribution opportunity sources."""

    @abstractmethod
    async def fetch_repos(
        self,
        profile: UserProfile,
        limit: int = 20,
    ) -> list[RepoResult]:
        """Fetch repos relevant to the user's profile."""
        ...

    @abstractmethod
    async def fetch_issues(
        self,
        profile: UserProfile,
        limit: int = 50,
    ) -> list[IssueResult]:
        """Fetch beginner-friendly issues relevant to the user's profile."""
        ...
```

Both methods are `async` — use `httpx.AsyncClient` for HTTP calls, which is passed in via the constructor.

---

## 2. Create the source file

Create `src/contrib_compass/sources/my_source.py`:

```python
"""
contrib_compass.sources.my_source — Fetch repos/issues from MySource.

Responsibility:
    Query the MySource API and return RepoResult / IssueResult objects.

NOT responsible for:
    - Scoring or ranking (see matching/)
    - Profile extraction (see profile/)

Key public API:
    MySource(client: httpx.AsyncClient, token: str = "")
        .fetch_repos(profile, limit) -> list[RepoResult]
        .fetch_issues(profile, limit) -> list[IssueResult]
"""

from __future__ import annotations

import logging

import httpx

from contrib_compass.models import Difficulty, IssueResult, RepoResult, UserProfile
from contrib_compass.sources.base import BaseSource

logger = logging.getLogger(__name__)

# Base URL for the MySource API
_BASE_URL = "https://api.mysource.example.com"


class MySource(BaseSource):
    """Fetch contribution opportunities from MySource.

    Args:
        client: Shared httpx.AsyncClient (manages connection pooling).
        token:  Optional API token for higher rate limits.
    """

    def __init__(self, client: httpx.AsyncClient, token: str = "") -> None:
        self._client = client
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def fetch_repos(
        self,
        profile: UserProfile,
        limit: int = 20,
    ) -> list[RepoResult]:
        """Fetch repos from MySource matching the user's skills.

        Args:
            profile: The user's skill profile.
            limit:   Maximum number of repos to return.

        Returns:
            List of RepoResult objects, unscored (score=0.0).
        """
        query = " ".join(profile.skills[:5])  # use top 5 skills as search terms
        try:
            resp = await self._client.get(
                f"{_BASE_URL}/search/repos",
                params={"q": query, "per_page": limit},
                headers=self._headers,
                timeout=10.0,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("MySource API error: %s", exc)
            return []

        results = []
        for item in resp.json().get("items", []):
            results.append(
                RepoResult(
                    full_name=item["full_name"],
                    description=item.get("description") or "",
                    url=item["html_url"],
                    stars=item.get("stargazers_count", 0),
                    language=item.get("language"),
                    topics=item.get("topics", []),
                    score=0.0,               # scored later by scorer.py
                    matched_skills=[],
                    source="mysource",       # identify which source this came from
                )
            )
        return results

    async def fetch_issues(
        self,
        profile: UserProfile,
        limit: int = 50,
    ) -> list[IssueResult]:
        """Fetch beginner-friendly issues from MySource.

        Args:
            profile: The user's skill profile.
            limit:   Maximum number of issues to return.

        Returns:
            List of IssueResult objects, unscored.
        """
        # Implementation varies by API — adapt as needed
        return []
```

---

## 3. Add the source to `_run_analysis`

Open `src/contrib_compass/web/router.py` and find the `_run_analysis` function.  Add your source alongside the existing ones:

```python
# In _run_analysis (around line 322):
from contrib_compass.sources.my_source import MySource   # add this import at top of file

async with httpx.AsyncClient(timeout=20.0) as client:
    github = GitHubSource(client=client)
    upforgrabs = UpForGrabsSource(client=client)
    mysource = MySource(client=client, token=settings.github_token)  # add this

    # ...existing fetches...

    try:
        my_repos = await mysource.fetch_repos(profile, limit=settings.max_repos)
    except Exception as exc:
        logger.warning("MySource fetch failed: %s", exc)
        my_repos = []
```

Then include `my_repos` in the merge step:

```python
for repo in gh_repos + ufg_repos + my_repos:   # add my_repos here
    ...
```

---

## 4. Write tests

Create `tests/sources/test_my_source.py`:

```python
"""Tests for MySource."""
import pytest
import respx
import httpx

from contrib_compass.sources.my_source import MySource
from contrib_compass.models import UserProfile


@pytest.fixture
def profile():
    return UserProfile(role="Backend Engineer", skills=["python", "fastapi"])


@pytest.mark.asyncio
async def test_fetch_repos_returns_results(profile):
    with respx.mock:
        respx.get("https://api.mysource.example.com/search/repos").mock(
            return_value=httpx.Response(200, json={
                "items": [
                    {
                        "full_name": "org/my-repo",
                        "description": "A Python FastAPI project",
                        "html_url": "https://github.com/org/my-repo",
                        "stargazers_count": 100,
                        "language": "Python",
                        "topics": ["python", "fastapi"],
                    }
                ]
            })
        )
        async with httpx.AsyncClient() as client:
            source = MySource(client=client)
            repos = await source.fetch_repos(profile, limit=10)

    assert len(repos) == 1
    assert repos[0].full_name == "org/my-repo"
    assert repos[0].source == "mysource"


@pytest.mark.asyncio
async def test_fetch_repos_handles_api_error(profile):
    with respx.mock:
        respx.get("https://api.mysource.example.com/search/repos").mock(
            return_value=httpx.Response(500)
        )
        async with httpx.AsyncClient() as client:
            source = MySource(client=client)
            repos = await source.fetch_repos(profile, limit=10)

    assert repos == []
```

---

## 5. Checklist

- [ ] Source class implements `BaseSource` (both `fetch_repos` and `fetch_issues`)
- [ ] HTTP errors are caught and logged, returning `[]` (never raise to the caller)
- [ ] `RepoResult.source` is set to a unique string identifier for your source
- [ ] Module-level docstring explains what the source does and its key public API
- [ ] All public methods have Google-style docstrings
- [ ] Tests added in `tests/sources/test_my_source.py`
- [ ] Source wired into `_run_analysis` in `router.py`
- [ ] PR title follows Conventional Commits: `feat(sources): add MySource`
