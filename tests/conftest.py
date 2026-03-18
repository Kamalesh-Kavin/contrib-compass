"""
tests/conftest.py — Shared pytest fixtures for contrib-compass.

Fixtures defined here are available in every test module automatically
(no import required — pytest auto-discovers conftest.py).

Key fixtures:
    sample_profile   — A pre-built UserProfile for most tests.
    sample_repo      — A pre-built RepoResult with realistic data.
    sample_issue     — A pre-built IssueResult with realistic data.
    mock_httpx_client — A respx-mocked AsyncClient for HTTP tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contrib_compass.models import (
    ContributionTip,
    Difficulty,
    IssueResult,
    RepoResult,
    UserProfile,
)

# ---------------------------------------------------------------------------
# Profile fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_profile() -> UserProfile:
    """A realistic UserProfile for use across multiple test modules."""
    return UserProfile(
        role="Backend Engineer",
        skills=["python", "fastapi", "postgresql", "docker", "redis"],
        languages=["python"],
        experience_years=3,
        bio="I build backend services with Python and FastAPI.",
        github_token="",
    )


@pytest.fixture
def sample_profile_with_token() -> UserProfile:
    """A UserProfile with a (fake) GitHub token."""
    return UserProfile(
        role="Full Stack Engineer",
        skills=["typescript", "react", "node", "postgres"],
        languages=["typescript", "javascript"],
        experience_years=5,
        github_token="ghp_faketoken123",
    )


# ---------------------------------------------------------------------------
# Result fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_repo() -> RepoResult:
    """A realistic RepoResult with all optional fields populated."""
    return RepoResult(
        full_name="tiangolo/fastapi",
        html_url="https://github.com/tiangolo/fastapi",
        description="FastAPI framework, high performance, easy to learn, fast to code.",
        language="Python",
        topics=["fastapi", "python", "api", "openapi"],
        stars=75000,
        forks=6000,
        open_issues=200,
        last_pushed_at=datetime(2026, 3, 1, tzinfo=UTC),
        keyword_score=0.8,
        semantic_score=0.9,
        final_score=0.86,
        tips=[
            ContributionTip(icon="📖", message="Has CONTRIBUTING.md", positive=True),
            ContributionTip(icon="🔥", message="Very active — pushed 15d ago", positive=True),
        ],
        matched_skills=["python", "fastapi"],
    )


@pytest.fixture
def sample_repo_minimal() -> RepoResult:
    """A minimal RepoResult with only required fields."""
    return RepoResult(
        full_name="owner/repo",
        html_url="https://github.com/owner/repo",
    )


@pytest.fixture
def sample_issue() -> IssueResult:
    """A realistic IssueResult."""
    return IssueResult(
        number=1234,
        title="Add support for async endpoints in documentation",
        html_url="https://github.com/tiangolo/fastapi/issues/1234",
        repo_full_name="tiangolo/fastapi",
        repo_html_url="https://github.com/tiangolo/fastapi",
        labels=["good first issue", "documentation"],
        comment_count=3,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 2, 1, tzinfo=UTC),
        difficulty=Difficulty.BEGINNER,
        difficulty_reason="Has 'good first issue' label",
        body_preview="We should add more examples for async endpoints in the docs.",
        matched_skills=["python", "fastapi"],
    )
