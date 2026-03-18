"""
tests/matching/test_keyword_matcher.py — Unit tests for keyword_matcher.

Tests cover:
  - score_repo: perfect overlap, partial overlap, zero overlap
  - score_issue: title match, label match, no match
  - Score bounds (always in [0, 1])
  - matched_skills accuracy
"""

from __future__ import annotations

from contrib_compass.matching.keyword_matcher import score_issue, score_repo

# ---------------------------------------------------------------------------
# score_repo
# ---------------------------------------------------------------------------


def test_score_repo_perfect_overlap():
    """When all user skills match repo topics/language, score should be high."""
    score, matched = score_repo(
        skills=["python", "fastapi"],
        description="FastAPI web framework for Python",
        topics=["fastapi", "python", "api"],
        language="Python",
    )
    assert score > 0.5
    assert "python" in matched or "fastapi" in matched


def test_score_repo_zero_overlap():
    """When no skills overlap with the repo at all, score should be 0.

    We use skills that cannot possibly substring-match any token in the target.
    """
    score, matched = score_repo(
        skills=["cobol", "fortran"],
        description="A CSS styling library",
        topics=["css", "design"],
        language="CSS",
    )
    assert score == 0.0
    assert matched == []


def test_score_repo_score_bounds():
    """score_repo should always return a float in [0, 1]."""
    for skills in [[], ["python"], ["python", "fastapi", "docker", "kubernetes"]]:
        score, _ = score_repo(
            skills=skills,
            description="Some repo description",
            topics=["python"],
            language="Python",
        )
        assert 0.0 <= score <= 1.0


def test_score_repo_empty_skills_returns_zero():
    """Empty skill list should result in a 0 score."""
    score, matched = score_repo(
        skills=[],
        description="Python FastAPI framework",
        topics=["python"],
        language="Python",
    )
    assert score == 0.0
    assert matched == []


def test_score_repo_none_description_does_not_crash():
    """None description should be handled gracefully."""
    score, _matched = score_repo(
        skills=["python"],
        description=None,
        topics=["python"],
        language="Python",
    )
    assert isinstance(score, float)


# ---------------------------------------------------------------------------
# score_issue
# ---------------------------------------------------------------------------


def test_score_issue_title_match():
    """Skill appearing in the issue title should increase score."""
    score, matched = score_issue(
        skills=["python", "documentation"],
        title="Improve Python documentation examples",
        labels=["good first issue"],
        repo_full_name="org/python-project",
    )
    assert score > 0.0
    assert "python" in matched or "documentation" in matched


def test_score_issue_label_match():
    """Skills matching issue labels should contribute to the score."""
    score, _matched = score_issue(
        skills=["typescript", "testing"],
        title="Fix a minor typo",
        labels=["typescript", "good first issue"],
        repo_full_name="org/ts-project",
    )
    assert score > 0.0


def test_score_issue_no_match():
    """When no skills appear in title, labels, or repo name, score = 0."""
    score, matched = score_issue(
        skills=["cobol", "fortran"],
        title="Update CSS styles for button",
        labels=["design"],
        repo_full_name="org/frontend-project",
    )
    assert score == 0.0
    assert matched == []


def test_score_issue_bounds():
    """score_issue should always return a float in [0, 1]."""
    score, _ = score_issue(
        skills=["python"] * 20,
        title="python python python",
        labels=["python"] * 10,
        repo_full_name="org/python",
    )
    assert 0.0 <= score <= 1.0
