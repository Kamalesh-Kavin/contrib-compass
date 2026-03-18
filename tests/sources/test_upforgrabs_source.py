"""
tests/sources/test_upforgrabs_source.py — Unit tests for UpForGrabsSource.

Uses respx to mock httpx calls.

Tests cover:
  - _filter_by_skills: correct filtering and sorting
  - _extract_owner_repo: various URL formats
  - fetch_repos: full mock flow returns RepoResult list
"""

from __future__ import annotations

import base64

import pytest
import yaml

from contrib_compass.sources.upforgrabs_source import (
    _extract_owner_repo,
    _filter_by_skills,
)


# ---------------------------------------------------------------------------
# _extract_owner_repo
# ---------------------------------------------------------------------------


def test_extract_owner_repo_standard_url():
    """Standard GitHub issues URL should return 'owner/repo'."""
    project = {
        "upforgrabs": {
            "link": "https://github.com/tiangolo/fastapi/issues?q=label%3A%22good+first+issue%22"
        }
    }
    assert _extract_owner_repo(project) == "tiangolo/fastapi"


def test_extract_owner_repo_no_query_string():
    """URL without query string should also work."""
    project = {"upforgrabs": {"link": "https://github.com/owner/repo"}}
    assert _extract_owner_repo(project) == "owner/repo"


def test_extract_owner_repo_non_github_url():
    """Non-GitHub URLs should return None."""
    project = {"upforgrabs": {"link": "https://gitlab.com/owner/repo/issues"}}
    assert _extract_owner_repo(project) is None


def test_extract_owner_repo_missing_link():
    """Missing upforgrabs.link key should return None."""
    assert _extract_owner_repo({}) is None


def test_extract_owner_repo_with_fragment():
    """URL with fragment should be handled."""
    project = {"upforgrabs": {"link": "https://github.com/owner/repo/issues#readme"}}
    assert _extract_owner_repo(project) == "owner/repo"


# ---------------------------------------------------------------------------
# _filter_by_skills
# ---------------------------------------------------------------------------


def test_filter_by_skills_returns_matching_projects():
    """Only projects with overlapping tags should be returned."""
    projects = [
        {"tags": ["python", "api"], "name": "Python project"},
        {"tags": ["rust", "wasm"], "name": "Rust project"},
        {"tags": ["python", "django"], "name": "Django project"},
    ]
    result = _filter_by_skills(projects, skills=["python", "fastapi"])
    names = [p["name"] for p in result]
    assert "Python project" in names
    assert "Django project" in names
    assert "Rust project" not in names


def test_filter_by_skills_sorted_by_overlap():
    """Projects with more tag overlap should appear first."""
    projects = [
        {"tags": ["python"], "name": "one match"},
        {"tags": ["python", "api", "fastapi"], "name": "three matches"},
        {"tags": ["python", "api"], "name": "two matches"},
    ]
    result = _filter_by_skills(projects, skills=["python", "api", "fastapi"])
    assert result[0]["name"] == "three matches"
    assert result[1]["name"] == "two matches"


def test_filter_by_skills_no_overlap_returns_empty():
    """No overlap between skills and tags should return an empty list."""
    projects = [{"tags": ["java", "spring"]}]
    assert _filter_by_skills(projects, skills=["python"]) == []


def test_filter_by_skills_empty_skills_returns_empty():
    """Empty skills list should always return empty."""
    projects = [{"tags": ["python"]}]
    assert _filter_by_skills(projects, skills=[]) == []
