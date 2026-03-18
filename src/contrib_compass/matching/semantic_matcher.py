"""
contrib_compass.matching.semantic_matcher — Sentence-transformers re-ranking.

Responsibility:
    Given a pre-loaded SentenceTransformer model, compute cosine similarity
    between a user query string and a list of target text strings.

NOT responsible for:
    - Loading the model (done once at app startup in main.py lifespan)
    - Combining scores with keyword scores (see scorer)

Model:
    Default: ``all-MiniLM-L6-v2``
    - ~80 MB
    - 384-dimensional embeddings
    - ~1–5ms per short string on CPU
    - Best for symmetric short-text similarity tasks

Why semantic re-ranking?
    Keyword matching misses synonyms: "ML" ≠ "machine learning" in a set,
    but they are semantically close.  Semantic re-ranking catches these.

Cache:
    The model is downloaded to ``SENTENCE_TRANSFORMERS_HOME`` on first use
    and cached for subsequent runs.  Set this env var to ``.cache/`` (the
    default) to keep the model inside the project.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Type alias to avoid importing SentenceTransformer at module level
# (it takes ~2s to import and would slow all tests that don't need it)
try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    SentenceTransformer = None  # type: ignore[assignment, misc]


def load_model(model_name: str, cache_dir: str) -> "SentenceTransformer":
    """Load a sentence-transformers model, caching it to ``cache_dir``.

    Called once during FastAPI's lifespan startup — NOT per request.

    Args:
        model_name: Model identifier (e.g. "all-MiniLM-L6-v2").
        cache_dir:  Absolute path to the model cache directory.
                    Set ``SENTENCE_TRANSFORMERS_HOME`` env var to this path.

    Returns:
        A loaded SentenceTransformer model instance.

    Raises:
        ImportError: If ``sentence-transformers`` is not installed.
        OSError: If the model cannot be downloaded (e.g. no internet).

    Example:
        >>> model = load_model("all-MiniLM-L6-v2", ".cache")
        >>> type(model).__name__
        'SentenceTransformer'
    """
    if not _ST_AVAILABLE:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Run: uv pip install sentence-transformers"
        )

    import os
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = cache_dir

    logger.info("Loading sentence-transformers model '%s' from cache '%s'", model_name, cache_dir)
    model = SentenceTransformer(model_name, cache_folder=cache_dir)
    logger.info("Model loaded successfully")
    return model


def score_texts(
    model: "SentenceTransformer",
    query: str,
    targets: list[str],
) -> list[float]:
    """Compute cosine similarity between a query and a list of target strings.

    All embeddings are computed in a single batch call for efficiency.

    Args:
        model:   A loaded SentenceTransformer model.
        query:   The user's skill summary string
                 (e.g. "python fastapi postgresql backend engineer").
        targets: List of target strings to score against
                 (e.g. repo descriptions or issue titles).

    Returns:
        List of float similarity scores in [0.0, 1.0], one per target.
        Returns a list of 0.0s if targets is empty or model is unavailable.

    Example:
        >>> scores = score_texts(model, "python fastapi", ["FastAPI REST API", "React frontend"])
        >>> scores[0] > scores[1]   # FastAPI is more similar
        True
    """
    if not targets:
        return []

    if model is None:
        logger.warning("No semantic model available — returning zero scores")
        return [0.0] * len(targets)

    try:
        all_texts = [query] + targets
        # encode() returns a numpy array of shape (N, embedding_dim)
        embeddings = model.encode(all_texts, convert_to_numpy=True, show_progress_bar=False)

        query_emb = embeddings[0]             # shape: (dim,)
        target_embs = embeddings[1:]          # shape: (N, dim)

        # Cosine similarity: dot product of L2-normalised vectors
        query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
        target_norms = target_embs / (np.linalg.norm(target_embs, axis=1, keepdims=True) + 1e-10)

        similarities = (target_norms @ query_norm).tolist()
        # Clip to [0, 1] — cosine can theoretically be negative for very different texts
        return [max(0.0, min(1.0, float(s))) for s in similarities]

    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic scoring failed: %s — returning zero scores", exc)
        return [0.0] * len(targets)


def build_query_string(profile_role: str, skills: list[str], bio: str = "") -> str:
    """Build a compact query string from a user profile for semantic encoding.

    The query is a short natural-language string that captures the user's
    technical identity.  Keeping it short (~50 tokens) prevents the model
    from averaging over too much noise.

    Args:
        profile_role: The user's job title / role.
        skills:       Normalised skill list.
        bio:          Optional free-form bio text (truncated to 100 chars).

    Returns:
        Query string, e.g.
        "Backend engineer skilled in python fastapi postgresql docker"

    Example:
        >>> build_query_string("Backend Engineer", ["python", "fastapi"])
        'backend engineer skilled in python fastapi'
    """
    skills_str = " ".join(skills[:15])  # top 15 skills max
    bio_snip = bio[:100].strip() if bio else ""

    parts = [f"{profile_role.lower()} skilled in {skills_str}"]
    if bio_snip:
        parts.append(bio_snip)

    return " ".join(parts)
