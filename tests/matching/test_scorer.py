"""
tests/matching/test_scorer.py — Unit tests for matching.scorer.

Tests cover:
  - rank_repos: output is sorted by final_score descending
  - rank_repos: empty input returns empty list
  - rank_issues: deduplicates by html_url
  - rank_issues: empty input returns empty list
  - Scores stay within [0, 1]

We pass model=None so no sentence-transformers is needed in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contrib_compass.matching.scorer import rank_issues, rank_repos
from contrib_compass.models import Difficulty, IssueResult, RepoResult, UserProfile


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(
        role="Backend Engineer",
        skills=["python", "fastapi", "postgresql"],
        languages=["python"],
    )


@pytest.fixture
def repos() -> list[RepoResult]:
    return [
        RepoResult(
            full_name="tiangolo/fastapi",
            html_url="https://github.com/tiangolo/fastapi",
            description="FastAPI framework",
            language="Python",
            topics=["fastapi", "python"],
            stars=75000,
        ),
        RepoResult(
            full_name="rust-lang/rust",
            html_url="https://github.com/rust-lang/rust",
            description="The Rust programming language",
            language="Rust",
            topics=["rust", "systems"],
            stars=90000,
        ),
    ]


@pytest.fixture
def issues() -> list[IssueResult]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        IssueResult(
            number=1,
            title="Add Python async example",
            html_url="https://github.com/tiangolo/fastapi/issues/1",
            repo_full_name="tiangolo/fastapi",
            repo_html_url="https://github.com/tiangolo/fastapi",
            labels=["good first issue"],
            created_at=now,
            updated_at=now,
            difficulty=Difficulty.BEGINNER,
        ),
        IssueResult(
            number=2,
            title="Fix CSS button style",
            html_url="https://github.com/org/frontend/issues/2",
            repo_full_name="org/frontend",
            repo_html_url="https://github.com/org/frontend",
            labels=["design"],
            created_at=now,
            updated_at=now,
            difficulty=Difficulty.BEGINNER,
        ),
    ]


# ---------------------------------------------------------------------------
# rank_repos
# ---------------------------------------------------------------------------


def test_rank_repos_returns_sorted(profile, repos):
    """rank_repos output should be sorted by final_score descending."""
    ranked = rank_repos(repos, profile, model=None)
    assert len(ranked) == 2
    assert ranked[0].final_score >= ranked[1].final_score


def test_rank_repos_empty_input(profile):
    """rank_repos with empty input should return an empty list."""
    assert rank_repos([], profile, model=None) == []


def test_rank_repos_scores_in_bounds(profile, repos):
    """All scores should be in [0, 1]."""
    for repo in rank_repos(repos, profile, model=None):
        assert 0.0 <= repo.final_score <= 1.0
        assert 0.0 <= repo.keyword_score <= 1.0
        assert 0.0 <= repo.semantic_score <= 1.0


def test_rank_repos_python_repo_ranked_higher(profile, repos):
    """Python FastAPI repo should rank higher than a Rust repo for a Python profile."""
    ranked = rank_repos(repos, profile, model=None)
    # tiangolo/fastapi should be first
    assert ranked[0].full_name == "tiangolo/fastapi"


# ---------------------------------------------------------------------------
# rank_issues
# ---------------------------------------------------------------------------


def test_rank_issues_returns_list(profile, issues):
    """rank_issues should return a list of IssueResult."""
    ranked = rank_issues(issues, profile, model=None)
    assert isinstance(ranked, list)
    assert len(ranked) == 2


def test_rank_issues_empty_input(profile):
    """rank_issues with empty input should return empty list."""
    assert rank_issues([], profile, model=None) == []


def test_rank_issues_deduplicates_by_url(profile, issues):
    """Duplicate issues (same html_url) should only appear once."""
    duplicate = issues[0]
    ranked = rank_issues([*issues, duplicate], profile, model=None)
    urls = [i.html_url for i in ranked]
    assert len(urls) == len(set(urls))
