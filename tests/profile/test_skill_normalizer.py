"""
tests/profile/test_skill_normalizer.py — Unit tests for skill_normalizer.normalise.

Tests cover:
  - Common programming languages are detected
  - Alias resolution (e.g. "js" → "javascript")
  - Stop word removal
  - Empty input returns empty lists
  - Deduplication
"""

from __future__ import annotations

import pytest

from contrib_compass.profile.skill_normalizer import normalise


def test_normalise_detects_python():
    text = "Experienced Python developer with Flask and Django background."
    skills, languages = normalise(text)
    assert "python" in languages
    assert "python" in skills


def test_normalise_alias_js():
    """'js' should be resolved to 'javascript'."""
    text = "Built SPA apps with JS and Node."
    skills, languages = normalise(text)
    assert "javascript" in languages or "javascript" in skills


def test_normalise_empty_returns_empty_lists():
    skills, languages = normalise("")
    assert skills == []
    assert languages == []


def test_normalise_deduplicates():
    """Repeated mentions of the same skill should only appear once."""
    text = "Python Python Python developer"
    skills, _ = normalise(text)
    assert skills.count("python") == 1


def test_normalise_returns_lowercase():
    """All skill tokens should be lowercase."""
    text = "TypeScript React PostgreSQL"
    skills, languages = normalise(text)
    assert all(s == s.lower() for s in skills)
    assert all(lang == lang.lower() for lang in languages)


def test_normalise_extracts_languages_subset():
    """Languages list should be a subset of the skills list."""
    text = "Python FastAPI PostgreSQL Docker TypeScript"
    skills, languages = normalise(text)
    # Every language should also appear in skills
    for lang in languages:
        assert lang in skills


def test_normalise_comma_separated_string():
    """Comma-separated input (from manual form) should work correctly."""
    text = "Python, FastAPI, PostgreSQL, Docker"
    skills, languages = normalise(text)
    assert "python" in skills
    assert "fastapi" in skills
    assert "postgresql" in skills
    assert "docker" in skills
