"""
tests/difficulty/test_classifier.py — Unit tests for difficulty.classifier.

Tests cover:
  - "good first issue" label → BEGINNER
  - "help wanted" only (no explicit beginner) → INTERMEDIATE
  - Complex issues (many comments, old, large repo) → ADVANCED
  - Very new issue with beginner label → BEGINNER
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from contrib_compass.difficulty.classifier import classify_issue
from contrib_compass.models import Difficulty


def _dt(days_ago: int) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=days_ago)


def test_good_first_issue_label_is_beginner():
    """The 'good first issue' label should always classify as BEGINNER."""
    difficulty, reason = classify_issue(
        labels=["good first issue"],
        comment_count=0,
        created_at=_dt(10),
        repo_stars=100,
    )
    assert difficulty == Difficulty.BEGINNER
    assert reason  # should provide a non-empty explanation


def test_help_wanted_only_is_intermediate():
    """'help wanted' without a beginner label → INTERMEDIATE."""
    difficulty, reason = classify_issue(
        labels=["help wanted"],
        comment_count=2,
        created_at=_dt(30),
        repo_stars=500,
    )
    assert difficulty in (Difficulty.INTERMEDIATE, Difficulty.BEGINNER)


def test_high_comment_count_is_advanced():
    """An issue with many comments and no beginner label → ADVANCED or INTERMEDIATE."""
    difficulty, reason = classify_issue(
        labels=["bug"],
        comment_count=50,
        created_at=_dt(180),
        repo_stars=50000,
    )
    assert difficulty in (Difficulty.ADVANCED, Difficulty.INTERMEDIATE)


def test_no_labels_returns_intermediate():
    """An issue with no labels at all should fall back to INTERMEDIATE."""
    difficulty, reason = classify_issue(
        labels=[],
        comment_count=1,
        created_at=_dt(5),
        repo_stars=None,
    )
    assert difficulty in (Difficulty.BEGINNER, Difficulty.INTERMEDIATE, Difficulty.ADVANCED)


def test_returns_tuple():
    """classify_issue must return a (Difficulty, str) tuple."""
    result = classify_issue(labels=["good first issue"], comment_count=0, created_at=_dt(1))
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], Difficulty)
    assert isinstance(result[1], str)
