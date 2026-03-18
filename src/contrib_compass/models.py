"""
contrib_compass.models — Shared Pydantic data models.

This module is the single source of truth for every data structure that flows
between layers of the application:

    UserProfile      — extracted from a resume or manual form input
    RepoResult       — a matched GitHub repository with scoring metadata
    IssueResult      — a matched GitHub issue with difficulty classification
    ContributionTip  — a human-readable tip about a repo (e.g. "Has CONTRIBUTING.md")
    AnalysisResult   — the complete output of one analysis run
    AnalysisStatus   — enum for the state of a background analysis task

Design notes:
- All models are immutable (frozen=True) to prevent accidental mutation after
  construction.
- Optional fields use ``None`` as default rather than empty strings / lists so
  callers can distinguish "not provided" from "empty".
- Timestamps are always timezone-aware UTC datetimes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Difficulty(StrEnum):
    """Estimated difficulty level for an open source issue."""

    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"


class AnalysisStatus(StrEnum):
    """Lifecycle state of a background analysis task."""

    PENDING = "pending"  # task queued but not started
    RUNNING = "running"  # task executing
    DONE = "done"  # task completed successfully
    ERROR = "error"  # task failed


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class UserProfile(BaseModel, frozen=True):
    """Structured representation of a user's skills and experience.

    Constructed either by parsing a resume file (pdf_parser / docx_parser)
    or from the manual form fields in the web UI.

    Attributes:
        role:        Job title / role the user identifies with (e.g. "Backend Engineer").
        skills:      Normalised list of technical skills (e.g. ["python", "fastapi"]).
        languages:   Programming languages only — used to filter GitHub repo results.
        experience_years: Self-reported years of experience; used to weight difficulty.
        bio:         Free-form summary used as additional semantic context.
        github_token: Optional PAT provided by the user for higher API rate limits.
    """

    role: str = Field(..., min_length=1, max_length=200, description="Job title / role")
    skills: list[str] = Field(default_factory=list, description="Normalised skill list")
    languages: list[str] = Field(
        default_factory=list,
        description="Programming languages only",
    )
    experience_years: int = Field(
        default=0, ge=0, le=50, description="Years of professional experience"
    )
    bio: str = Field(default="", max_length=2000, description="Free-form user bio")
    github_token: str = Field(
        default="",
        description="User-supplied GitHub PAT; never persisted to disk",
    )

    @field_validator("skills", "languages", mode="before")
    @classmethod
    def _deduplicate_lowercase(cls, v: list[str]) -> list[str]:
        """Lowercase and deduplicate skill / language lists."""
        seen: set[str] = set()
        result: list[str] = []
        for item in v:
            normalised = item.strip().lower()
            if normalised and normalised not in seen:
                seen.add(normalised)
                result.append(normalised)
        return result


# ---------------------------------------------------------------------------
# Enrichment sub-models
# ---------------------------------------------------------------------------


class ContributionTip(BaseModel, frozen=True):
    """A single human-readable tip about how easy it is to contribute to a repo.

    Attributes:
        icon:    Single emoji used in the UI (e.g. "📖").
        message: Short tip text (e.g. "Has CONTRIBUTING.md").
        positive: True → green badge; False → amber/red badge.
    """

    icon: str
    message: str
    positive: bool = True


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class RepoResult(BaseModel, frozen=True):
    """A matched GitHub repository.

    Attributes:
        full_name:       e.g. "tiangolo/fastapi"
        html_url:        Link to the repo on GitHub.
        description:     Repo description (may be None if the owner left it blank).
        language:        Primary language reported by GitHub (may be None).
        topics:          GitHub topics list.
        stars:           Star count at time of analysis.
        forks:           Fork count at time of analysis.
        open_issues:     Number of open issues at time of analysis.
        last_pushed_at:  UTC datetime of the last push.
        keyword_score:   Raw keyword-overlap score (0.0 - 1.0).
        semantic_score:  Cosine similarity score from sentence-transformers (0.0 - 1.0).
        final_score:     Weighted combination of keyword + semantic scores (0.0 - 1.0).
        tips:            Enrichment tips (CONTRIBUTING.md, activity, etc.).
        matched_skills:  Which user skills contributed to the match (for UI display).
    """

    full_name: str
    html_url: str
    description: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    last_pushed_at: datetime | None = None
    keyword_score: float = Field(ge=0.0, le=1.0, default=0.0)
    semantic_score: float = Field(ge=0.0, le=1.0, default=0.0)
    final_score: float = Field(ge=0.0, le=1.0, default=0.0)
    tips: list[ContributionTip] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)

    @property
    def last_pushed_days_ago(self) -> int | None:
        """Days since the last push, or None if unknown."""
        if self.last_pushed_at is None:
            return None
        now = datetime.now(tz=UTC)
        # Ensure last_pushed_at is timezone-aware
        lp = self.last_pushed_at
        if lp.tzinfo is None:
            lp = lp.replace(tzinfo=UTC)
        return (now - lp).days


class IssueResult(BaseModel, frozen=True):
    """A matched GitHub issue.

    Attributes:
        number:        Issue number within its repo.
        title:         Issue title.
        html_url:      Link to the issue on GitHub.
        repo_full_name: e.g. "tiangolo/fastapi"
        repo_html_url: Link to the parent repo.
        labels:        All label names on the issue.
        comment_count: Number of comments on the issue.
        created_at:    UTC datetime when the issue was opened.
        updated_at:    UTC datetime of the last update.
        difficulty:    Estimated difficulty classification.
        difficulty_reason: Short explanation of why this difficulty was assigned.
        body_preview:  First 300 characters of the issue body (may be None).
        matched_skills: Which user skills contributed to the match (for UI display).
    """

    number: int
    title: str
    html_url: str
    repo_full_name: str
    repo_html_url: str
    labels: list[str] = Field(default_factory=list)
    comment_count: int = 0
    created_at: datetime
    updated_at: datetime
    difficulty: Difficulty = Difficulty.INTERMEDIATE
    difficulty_reason: str = ""
    body_preview: str | None = None
    matched_skills: list[str] = Field(default_factory=list)

    @property
    def age_days(self) -> int:
        """Days since the issue was opened."""
        now = datetime.now(tz=UTC)
        ca = self.created_at
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=UTC)
        return (now - ca).days


# ---------------------------------------------------------------------------
# Top-level analysis result
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel, frozen=True):
    """The complete output of one analysis run.

    Attributes:
        session_id:   UUID that identifies this analysis session.
        status:       Current lifecycle state.
        profile:      The UserProfile used for this analysis.
        repos:        Ranked list of matching repos.
        issues:       Ranked list of matching issues.
        error:        Human-readable error message (only set when status=ERROR).
        created_at:   UTC datetime when the analysis was started.
        completed_at: UTC datetime when the analysis finished (None if still running).
        rate_limit_warning: True if GitHub rate limits were hit during analysis.
    """

    session_id: str
    status: AnalysisStatus = AnalysisStatus.PENDING
    profile: UserProfile | None = None
    repos: list[RepoResult] = Field(default_factory=list)
    issues: list[IssueResult] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime | None = None
    rate_limit_warning: bool = False
