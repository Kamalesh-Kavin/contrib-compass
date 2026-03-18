# Skill matching

This document explains how ContribCompass scores and ranks repos and issues against a user's skill profile.

---

## Overview

Scoring is a two-stage pipeline:

```
UserProfile (skills, languages, role)
        │
        ├── keyword_matcher.py  ─── keyword_score  (40%)
        │                                │
        └── semantic_matcher.py ─── semantic_score (60%)
                                         │
                                         ▼
                                    final_score = 0.4 × keyword + 0.6 × semantic
```

Both scores are in the range `[0.0, 1.0]`.  The final score determines the sort order in the results page.

---

## Stage 1: Keyword matching (`matching/keyword_matcher.py`)

### Algorithm

1. Build a set of **target tokens** from the repo/issue metadata:
   - All words from the description (split on non-alphanumeric characters)
   - All GitHub topics (kept whole *and* split on hyphens, e.g. `machine-learning` → `machine`, `learning`, `machine-learning`)
   - The primary language (e.g. `python`)

2. For each user skill, check if it appears in the target token set:
   - **Exact match**: `skill in target_tokens`
   - **Substring match** (both directions, min 4 chars each): `skill in token or token in skill`

3. The raw score is:

   ```
   keyword_score = |matched_skills| / |user_skills|
   ```

   Capped at 1.0.

### Why substring matching?

GitHub topic names often use compound forms like `fastapi-users` or `react-native`.  Substring matching lets `fastapi` match `fastapi-users` without requiring an exact topic name.

The 4-character minimum prevents short English prepositions (`for`, `in`, `at`) from incorrectly matching skills like `fortran` or `interface`.

### Issue scoring

For issues, the target tokens are built from:
- The issue title
- All label names
- The repo's `full_name` (e.g. `tiangolo/fastapi` contributes `tiangolo` and `fastapi`)

---

## Stage 2: Semantic matching (`matching/semantic_matcher.py`)

### Model

`sentence-transformers/all-MiniLM-L6-v2` — a lightweight, fast sentence embedding model (~90 MB, ~400 MB RAM at inference) that produces 384-dimensional vectors.

The model is loaded once during app startup (FastAPI lifespan) and stored in `app.state.model`.  If the model failed to load, semantic scoring falls back to `0.0` and results are ranked by keyword score only.

### Algorithm

1. Build a **user query string** from the profile:

   ```
   "{role} developer with experience in {skill1}, {skill2}, ..."
   ```

2. Build a **target string** from the repo/issue:
   - Repo: `"{description} {' '.join(topics)} {language}"`
   - Issue: `"{title} {' '.join(labels)}"`

3. Encode both strings using the model to get unit-norm embeddings.

4. Compute cosine similarity:

   ```
   semantic_score = max(0.0, cosine_similarity(user_vec, target_vec))
   ```

   Negative cosine similarities are clamped to 0.

### Why 60% semantic weight?

Keyword matching is fast and precise but brittle:
- It misses synonyms ("ML" vs "machine learning")
- It misses closely related concepts ("FastAPI" vs "async web framework")

Semantic similarity handles these cases.  We weight it higher (60%) because it captures intent better, but we keep keyword matching (40%) to ensure obviously-matching repos aren't buried.

---

## Combining scores (`matching/scorer.py`)

```python
final_score = round(0.4 * keyword_score + 0.6 * semantic_score, 4)
```

`scorer.rank_repos` and `scorer.rank_issues` call both matchers and sort descending by `final_score`.

### Matched skills

The `matched_skills` list attached to each result comes from the keyword matcher.  It's shown in the UI as skill chips on each repo card.

---

## Tuning the weights

The `0.4 / 0.6` split is a heuristic.  If you want to experiment:

1. Edit `scorer.py`:

   ```python
   KEYWORD_WEIGHT = 0.4   # increase for more exact-match bias
   SEMANTIC_WEIGHT = 0.6  # increase for more concept-match bias
   ```

2. Run the tests — the scorer tests use specific expected score ranges so you may need to update assertions.

3. Validate the change by manually checking a few results against your own profile.

---

## Difficulty classification (`difficulty/classifier.py`)

Issues are classified as `easy`, `medium`, or `hard` after scoring.  This is separate from the relevance score.

The classifier uses a priority cascade:

1. **Label-based** (highest confidence): labels like `good first issue` → easy, `help wanted` → easy/medium, `difficulty: hard` → hard.
2. **Title heuristics**: words like "fix typo" → easy, "implement" → medium, "refactor" / "research" → hard.
3. **Body length proxy**: short body (<200 chars) → easy bias; very long body (>1000 chars) → hard bias.

The final difficulty is used for the filter chips on the results page.
