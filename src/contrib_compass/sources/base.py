"""
contrib_compass.sources.base — Source protocol definition.

Defines the interface that every data source adapter must implement.
This allows the scorer to work with any source interchangeably.

To add a new data source:
1. Create a new module in sources/ (e.g. sources/gitlab_source.py).
2. Implement a class that satisfies the ``Source`` protocol below.
3. Register it in web/router.py alongside the existing sources.
4. Follow the guide in docs/adding-a-source.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contrib_compass.models import IssueResult, RepoResult, UserProfile


@runtime_checkable
class Source(Protocol):
    """Protocol that all data source adapters must satisfy.

    A source is responsible for fetching raw candidate repos and issues from
    an external service.  It does NOT perform scoring or filtering — that is
    done by the matching layer.
    """

    async def fetch_repos(
        self,
        profile: UserProfile,
        limit: int = 20,
    ) -> list[RepoResult]:
        """Fetch candidate repositories matching the user's profile.

        Args:
            profile: The user's normalised profile.
            limit:   Maximum number of repos to return.

        Returns:
            List of RepoResult objects with keyword_score=0, semantic_score=0,
            final_score=0 (scores are assigned by the matching layer).
        """
        ...

    async def fetch_issues(
        self,
        profile: UserProfile,
        limit: int = 50,
    ) -> list[IssueResult]:
        """Fetch candidate issues matching the user's profile.

        Args:
            profile: The user's normalised profile.
            limit:   Maximum number of issues to return.

        Returns:
            List of IssueResult objects (difficulty is pre-classified by
            the source using the difficulty.classifier module).
        """
        ...
