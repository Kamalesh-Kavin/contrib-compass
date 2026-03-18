"""
contrib_compass.matching.scorer — Combine keyword + semantic scores into ranked results.

Responsibility:
    Take raw (unscored) repos and issues from data sources, apply keyword
    scoring, apply semantic re-ranking, combine into a final score, and
    return a deduplicated, sorted list.

NOT responsible for:
    - Fetching data (see sources/)
    - Enrichment tips (see enrichment/)

Scoring formula:
    final_score = (KEYWORD_WEIGHT * keyword_score) + (SEMANTIC_WEIGHT * semantic_score)

    KEYWORD_WEIGHT  = 0.4
    SEMANTIC_WEIGHT = 0.6

    Rationale: Semantic scores capture synonyms and conceptual similarity
    that keyword overlap misses.  We still include keyword scores because
    they provide a strong exact-match signal (e.g. "python" in topics).

    These weights are tunable — see docs/skill-matching.md.
"""

from __future__ import annotations

import logging

from contrib_compass.matching import keyword_matcher, semantic_matcher
from contrib_compass.models import IssueResult, RepoResult, UserProfile

logger = logging.getLogger(__name__)

# Scoring weights — must sum to 1.0
KEYWORD_WEIGHT: float = 0.4
SEMANTIC_WEIGHT: float = 0.6


def rank_repos(
    repos: list[RepoResult],
    profile: UserProfile,
    model: object,  # SentenceTransformer | None
) -> list[RepoResult]:
    """Score and rank a list of repos against a user profile.

    Pipeline:
    1. Keyword score each repo.
    2. Semantic score all repos in a single batch (efficient).
    3. Combine scores with KEYWORD_WEIGHT / SEMANTIC_WEIGHT.
    4. Sort by final_score descending.
    5. Attach matched_skills to each RepoResult.

    Args:
        repos:   Raw unscored RepoResult list from source adapters.
        profile: The user's normalised profile.
        model:   Loaded SentenceTransformer model (or None to skip semantic).

    Returns:
        Sorted list of RepoResult objects with scores populated.
    """
    if not repos:
        return []

    query = semantic_matcher.build_query_string(profile.role, profile.skills, profile.bio)

    # ── Step 1: Keyword scores ─────────────────────────────────────────────
    kw_scores: list[float] = []
    matched_skills_list: list[list[str]] = []

    for repo in repos:
        score, matched = keyword_matcher.score_repo(
            skills=profile.skills,
            description=repo.description,
            topics=repo.topics,
            language=repo.language,
        )
        kw_scores.append(score)
        matched_skills_list.append(matched)

    # ── Step 2: Semantic scores (batched) ──────────────────────────────────
    target_texts = [
        _repo_to_text(repo) for repo in repos
    ]
    sem_scores = semantic_matcher.score_texts(model, query, target_texts)

    # ── Step 3 & 4: Combine and sort ──────────────────────────────────────
    scored: list[RepoResult] = []
    for repo, kw, sem, matched in zip(repos, kw_scores, sem_scores, matched_skills_list):
        final = round(KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem, 4)
        scored.append(
            RepoResult(
                **{
                    **repo.model_dump(),
                    "keyword_score": kw,
                    "semantic_score": sem,
                    "final_score": final,
                    "matched_skills": matched,
                }
            )
        )

    scored.sort(key=lambda r: r.final_score, reverse=True)
    logger.debug("Ranked %d repos; top score=%.3f", len(scored), scored[0].final_score if scored else 0)
    return scored


def rank_issues(
    issues: list[IssueResult],
    profile: UserProfile,
    model: object,  # SentenceTransformer | None
) -> list[IssueResult]:
    """Score and rank a list of issues against a user profile.

    Args:
        issues:  Raw IssueResult list from source adapters.
        profile: The user's normalised profile.
        model:   Loaded SentenceTransformer model (or None to skip semantic).

    Returns:
        Sorted list of IssueResult objects with matched_skills populated.
        Issues are deduplicated by html_url before ranking.
    """
    if not issues:
        return []

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[IssueResult] = []
    for issue in issues:
        if issue.html_url not in seen:
            seen.add(issue.html_url)
            unique.append(issue)

    query = semantic_matcher.build_query_string(profile.role, profile.skills, profile.bio)

    # ── Keyword scores ─────────────────────────────────────────────────────
    kw_scores: list[float] = []
    matched_skills_list: list[list[str]] = []

    for issue in unique:
        score, matched = keyword_matcher.score_issue(
            skills=profile.skills,
            title=issue.title,
            labels=issue.labels,
            repo_full_name=issue.repo_full_name,
        )
        kw_scores.append(score)
        matched_skills_list.append(matched)

    # ── Semantic scores ────────────────────────────────────────────────────
    target_texts = [
        f"{issue.title} {issue.repo_full_name} {' '.join(issue.labels)}"
        for issue in unique
    ]
    sem_scores = semantic_matcher.score_texts(model, query, target_texts)

    # ── Combine and sort ───────────────────────────────────────────────────
    scored: list[tuple[float, IssueResult]] = []
    for issue, kw, sem, matched in zip(unique, kw_scores, sem_scores, matched_skills_list):
        final = round(KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem, 4)
        updated = IssueResult(**{**issue.model_dump(), "matched_skills": matched})
        scored.append((final, updated))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [issue for _, issue in scored]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_to_text(repo: RepoResult) -> str:
    """Build a single text string representing a repo for semantic encoding.

    Args:
        repo: A RepoResult object.

    Returns:
        Concatenated text string (description + topics + language).
    """
    parts: list[str] = []
    if repo.description:
        parts.append(repo.description)
    if repo.topics:
        parts.append(" ".join(repo.topics))
    if repo.language:
        parts.append(repo.language)
    if repo.full_name:
        # e.g. "tiangolo/fastapi" → "fastapi"
        parts.append(repo.full_name.split("/")[-1].replace("-", " "))
    return " ".join(parts) or repo.full_name
