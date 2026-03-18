"""
contrib_compass.difficulty.classifier — Heuristic issue difficulty classification.

Responsibility:
    Classify a GitHub issue as Beginner / Intermediate / Advanced based on
    observable signals available without reading the issue body.

NOT responsible for:
    - Semantic analysis of issue text (no ML here)
    - Fetching issue data (that's the source's job)

Algorithm (signal → weight):
    1. Labels — strongest signal
       - "good first issue", "starter", "beginner" → Beginner
       - "help wanted" alone → Intermediate
       - "bug", "performance", "security", "refactor" → push toward Advanced
    2. Comment count — social activity proxy
       - 0–2 → leans Beginner
       - 3–8 → Intermediate
       - 9+  → Advanced (heavily discussed = complex)
    3. Issue age (days open)
       - > 90 days → possibly difficult (nobody has tackled it)
       - < 7 days  → fresh, may be easier
    4. Repo stars (optional, passed as None from search results)
       - > 5 000   → large project, likely higher bar

Each signal contributes a score delta.  The final classification is the
bucket that accumulates the highest score.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contrib_compass.models import Difficulty

# ---------------------------------------------------------------------------
# Label keywords mapped to difficulty signals
# ---------------------------------------------------------------------------

# Labels that strongly indicate a beginner-friendly issue
_BEGINNER_LABELS: frozenset[str] = frozenset(
    {
        "good first issue",
        "good-first-issue",
        "goodfirstissue",
        "starter",
        "beginner",
        "beginner friendly",
        "easy",
        "first timer",
        "first-timers-only",
        "hacktoberfest",
        "low hanging fruit",
        "newcomer",
        "trivial",
    }
)

# Labels that suggest intermediate work
_INTERMEDIATE_LABELS: frozenset[str] = frozenset(
    {
        "help wanted",
        "help-wanted",
        "enhancement",
        "feature",
        "feature request",
        "improvement",
        "documentation",
        "docs",
        "test",
        "testing",
    }
)

# Labels that suggest advanced / complex work
_ADVANCED_LABELS: frozenset[str] = frozenset(
    {
        "bug",
        "performance",
        "security",
        "refactor",
        "refactoring",
        "architecture",
        "breaking change",
        "core",
        "critical",
        "regression",
        "needs investigation",
        "rfc",
        "design",
    }
)


def classify_issue(
    labels: list[str],
    comment_count: int,
    created_at: datetime,
    repo_stars: int | None = None,
) -> tuple[Difficulty, str]:
    """Classify an issue's difficulty and explain the reasoning.

    Args:
        labels:        List of label names on the issue.
        comment_count: Number of comments on the issue.
        created_at:    UTC datetime when the issue was opened.
        repo_stars:    Star count of the parent repo (None if unknown).

    Returns:
        A tuple ``(Difficulty, reason_string)`` where reason is a short
        human-readable explanation shown in the UI.

    Example:
        >>> from datetime import datetime, timezone, timedelta
        >>> d, r = classify_issue(
        ...     labels=["good first issue"],
        ...     comment_count=1,
        ...     created_at=datetime.now(tz=timezone.utc) - timedelta(days=10),
        ... )
        >>> d
        <Difficulty.BEGINNER: 'Beginner'>
    """
    scores: dict[Difficulty, float] = {
        Difficulty.BEGINNER: 0.0,
        Difficulty.INTERMEDIATE: 0.0,
        Difficulty.ADVANCED: 0.0,
    }
    reasons: list[str] = []

    # ── Signal 1: Labels ─────────────────────────────────────────────────
    normalised_labels = {lb.lower() for lb in labels}

    if normalised_labels & _BEGINNER_LABELS:
        scores[Difficulty.BEGINNER] += 3.0
        matched = normalised_labels & _BEGINNER_LABELS
        reasons.append(f"labeled '{next(iter(matched))}'")

    if normalised_labels & _INTERMEDIATE_LABELS:
        scores[Difficulty.INTERMEDIATE] += 2.0

    if normalised_labels & _ADVANCED_LABELS:
        scores[Difficulty.ADVANCED] += 2.5
        matched = normalised_labels & _ADVANCED_LABELS
        reasons.append(f"labeled '{next(iter(matched))}'")

    # ── Signal 2: Comment count ──────────────────────────────────────────
    if comment_count <= 2:
        scores[Difficulty.BEGINNER] += 1.0
    elif comment_count <= 8:
        scores[Difficulty.INTERMEDIATE] += 1.0
        reasons.append(f"{comment_count} comments")
    else:
        scores[Difficulty.ADVANCED] += 1.5
        reasons.append(f"{comment_count} comments (actively discussed)")

    # ── Signal 3: Issue age ──────────────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    ca = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    age_days = (now - ca).days

    if age_days > 90:
        # Long-open issues tend to be tricky or low-priority
        scores[Difficulty.ADVANCED] += 0.5
        reasons.append(f"open {age_days}d")
    elif age_days < 7:
        scores[Difficulty.BEGINNER] += 0.5
        reasons.append("fresh issue")

    # ── Signal 4: Repo star count ────────────────────────────────────────
    if repo_stars is not None:
        if repo_stars > 5000:
            scores[Difficulty.ADVANCED] += 1.0
            reasons.append(f"{repo_stars:,} stars")
        elif repo_stars > 500:
            scores[Difficulty.INTERMEDIATE] += 0.5

    # ── Final classification ─────────────────────────────────────────────
    difficulty = max(scores, key=lambda d: scores[d])

    # Build reason string
    if not reasons:
        reasons.append("based on issue metadata")
    reason = "; ".join(reasons)

    return difficulty, reason
