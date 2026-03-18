"""
contrib_compass.matching.keyword_matcher — Fast keyword-overlap scoring.

Responsibility:
    Given a user's skill list and a target text (repo description + topics
    + language), compute a raw overlap score between 0.0 and 1.0.

NOT responsible for:
    - Semantic similarity (see semantic_matcher)
    - Final ranking (see scorer)

Algorithm:
    Score = |user_skills ∩ target_tokens| / min(|user_skills|, 10)

    The denominator is capped at 10 so that users with very long skill lists
    (e.g. 40 skills from a detailed resume) aren't penalised by the maths.
    A repo that matches 3 of your 40 skills is a reasonable match — it shouldn't
    score 0.075 just because your resume is thorough.

    Where target_tokens includes:
    - Individual words from the description (lowercased)
    - Repo topics (lowercased)
    - Primary language (lowercased)

    We also check for substring matches (e.g. "fastapi" in "fastapi-users")
    to handle compound tokens.
"""

from __future__ import annotations

import re

# Tokenise a sentence into lowercase words
_WORD_RE = re.compile(r"[a-z0-9#+\-.]+")

# Cap the denominator to avoid penalising users with many skills.
# A user with 5 matching skills out of 40 total still scores 5/10 = 0.5
# rather than 5/40 = 0.125.
_SCORE_DENOMINATOR_CAP = 10


def score_repo(
    skills: list[str],
    description: str | None,
    topics: list[str],
    language: str | None,
) -> tuple[float, list[str]]:
    """Score a repo against a user's skill list using keyword overlap.

    Args:
        skills:      Normalised user skill list.
        description: Repo description string (may be None).
        topics:      GitHub topics list.
        language:    Primary programming language (may be None).

    Returns:
        A tuple ``(score, matched_skills)`` where:
        - ``score`` is a float in [0.0, 1.0]
        - ``matched_skills`` is the list of user skills that matched

    Example:
        >>> score_repo(["python", "fastapi"], "A FastAPI web framework", ["fastapi"], "Python")
        (1.0, ['python', 'fastapi'])
    """
    if not skills:
        return 0.0, []

    target_tokens = _build_target_tokens(description, topics, language)
    return _overlap_score(skills, target_tokens)


def score_issue(
    skills: list[str],
    title: str,
    labels: list[str],
    repo_full_name: str,
    body_preview: str | None = None,
) -> tuple[float, list[str]]:
    """Score an issue against a user's skill list using keyword overlap.

    Args:
        skills:        Normalised user skill list.
        title:         Issue title.
        labels:        Issue label names.
        repo_full_name: e.g. "tiangolo/fastapi" — repo name is also a signal.
        body_preview:  First ~300 chars of the issue body (optional but improves matching).

    Returns:
        A tuple ``(score, matched_skills)``.

    Example:
        >>> score_issue(
        ...     ["python", "fastapi"], "Add FastAPI middleware support", [], "tiangolo/fastapi"
        ... )
        (0.5, ['fastapi'])
    """
    if not skills:
        return 0.0, []

    # Build target from title words + label words + repo name parts + body preview
    body_part = body_preview or ""
    combined = f"{title} {' '.join(labels)} {repo_full_name.replace('/', ' ')} {body_part}"
    target_tokens = set(_WORD_RE.findall(combined.lower()))
    return _overlap_score(skills, target_tokens)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_target_tokens(
    description: str | None,
    topics: list[str],
    language: str | None,
) -> set[str]:
    """Build the set of target tokens from repo metadata.

    Args:
        description: Repo description (may be None).
        topics:      GitHub topics.
        language:    Primary language.

    Returns:
        Set of lowercase token strings.
    """
    tokens: set[str] = set()

    if description:
        tokens.update(_WORD_RE.findall(description.lower()))

    for topic in topics:
        # Keep topics whole (e.g. "machine-learning") and also split on hyphens
        tokens.add(topic.lower())
        tokens.update(topic.lower().replace("-", " ").split())

    if language:
        tokens.add(language.lower())

    return tokens


def _overlap_score(
    skills: list[str],
    target_tokens: set[str],
) -> tuple[float, list[str]]:
    """Compute overlap score between skill list and target token set.

    Checks both exact match and substring containment.  Uses a capped
    denominator so users with very long skill lists aren't unfairly penalised.

    Args:
        skills:        User skill list (lowercased).
        target_tokens: Set of tokens from the target.

    Returns:
        ``(score, matched_skills)``
    """
    matched: list[str] = []

    for skill in skills:
        # Exact match
        if skill in target_tokens:
            matched.append(skill)
            continue
        # Substring match: skill appears inside any target token or vice-versa.
        # Only consider tokens long enough to avoid false positives (e.g. "for"
        # inside "fortran" would otherwise incorrectly match a skill "fortran").
        # We require both the skill and the token to be at least 4 chars long
        # before applying substring matching.
        for token in target_tokens:
            if len(skill) >= 4 and len(token) >= 4:
                if skill in token or token in skill:
                    matched.append(skill)
                    break

    # Cap denominator at _SCORE_DENOMINATOR_CAP so that users with many skills
    # don't receive artificially low scores for repos that match several skills.
    denominator = min(len(skills), _SCORE_DENOMINATOR_CAP)
    score = len(matched) / denominator if denominator > 0 else 0.0
    return round(min(score, 1.0), 4), matched
