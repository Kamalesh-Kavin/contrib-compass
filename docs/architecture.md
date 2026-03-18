# Architecture

This document describes the internal structure of ContribCompass — how data flows from a user's resume (or form input) to a ranked list of contribution opportunities.

---

## High-level overview

```
Browser
  │
  │  POST /analyze  (multipart form: resume file OR text fields)
  ▼
┌──────────────────────────────────────────────────────────────┐
│                        FastAPI app                           │
│                       (main.py)                              │
│                                                              │
│  1. Profile extraction                                       │
│     profile/extractor.py                                     │
│       ├── pdf_parser.py      — extract raw text from PDF     │
│       ├── docx_parser.py     — extract raw text from DOCX    │
│       └── skill_normalizer.py — tokenise + alias-resolve     │
│                 │                                            │
│                 │  UserProfile (models.py)                   │
│                 ▼                                            │
│  2. Background analysis task  (_run_analysis in router.py)   │
│       ├── sources/github_source.py  — GitHub Search API      │
│       │     ├── fetch_repos(profile, limit)                  │
│       │     └── fetch_issues(profile, limit)                 │
│       ├── sources/upforgrabs_source.py — YAML feed           │
│       │     └── fetch_repos(profile, limit)                  │
│       │                                                      │
│       │  Repo + Issue objects (models.py)                    │
│       ▼                                                      │
│  3. Scoring  (matching/)                                     │
│       ├── keyword_matcher.py  — fast overlap score (40%)     │
│       ├── semantic_matcher.py — MiniLM cosine score (60%)    │
│       └── scorer.py           — combine + rank               │
│                 │                                            │
│                 ▼                                            │
│  4. Enrichment  (enrichment/repo_enricher.py)               │
│       — Fetch README snippet, contributing guide hint        │
│                 │                                            │
│                 ▼                                            │
│  5. Session store  (web/session.py)                         │
│       — in-memory dict, TTL eviction, asyncio.Lock           │
└──────────────────────────────────────────────────────────────┘
  │
  │  GET /status/{id}  (JS polling, every 2s)
  │  GET /results/{id} (redirect when done)
  ▼
Browser renders results.html (Tailwind cards + issue table)
```

---

## Module reference

### `config.py`

Reads all configuration from environment variables using `pydantic-settings`.  A single `Settings` instance is created at import time via `get_settings()` (cached with `@lru_cache`).

Key settings:
- `GITHUB_TOKEN` — optional PAT for higher API rate limits
- `MAX_REPOS`, `MAX_ISSUES` — caps on result counts
- `SESSION_TTL_SECONDS` — how long sessions survive in memory

### `models.py`

Pydantic v2 data models shared across the whole app:

| Model | Purpose |
|-------|---------|
| `UserProfile` | Skills, languages, role, years of experience |
| `RepoResult` | A GitHub/Up For Grabs repo with score metadata |
| `IssueResult` | A GitHub issue with difficulty + matched skills |
| `AnalysisResult` | Top-level session result: repos + issues + status |
| `AnalysisStatus` | Enum: `PENDING`, `RUNNING`, `DONE`, `ERROR` |

### `profile/`

Responsible for turning raw bytes or form text into a `UserProfile`.

- `pdf_parser.py` — uses PyMuPDF (`fitz`) to extract text page-by-page
- `docx_parser.py` — uses `python-docx` to extract paragraphs and table cells
- `skill_normalizer.py` — tokenises text, applies alias map (JS → javascript), removes stop words, deduplicates
- `extractor.py` — orchestrates the above; dispatches by file type

### `sources/`

Each source implements the `BaseSource` abstract class (defined in `base.py`):

```python
class BaseSource(ABC):
    async def fetch_repos(self, profile: UserProfile, limit: int) -> list[RepoResult]: ...
    async def fetch_issues(self, profile: UserProfile, limit: int) -> list[IssueResult]: ...
```

- `github_source.py` — queries `api.github.com/search/repositories` and `.../issues` using the user's skills as search keywords.  Handles `RateLimitError` gracefully.
- `upforgrabs_source.py` — fetches the Up For Grabs YAML registry from GitHub Contents API, parses each project entry, and returns repos + issues tagged as beginner-friendly.

### `matching/`

Two complementary scorers are combined in `scorer.py`:

| Scorer | Weight | Method |
|--------|--------|--------|
| `keyword_matcher.py` | 40% | Exact + substring overlap between skill tokens and repo metadata tokens |
| `semantic_matcher.py` | 60% | Cosine similarity using `all-MiniLM-L6-v2` sentence embeddings |

**Scoring formula:**

```
final_score = 0.4 × keyword_score + 0.6 × semantic_score
```

Both scores are in `[0, 1]`.  `scorer.rank_repos` and `scorer.rank_issues` sort results descending by `final_score`.

### `difficulty/classifier.py`

Classifies each issue as `easy`, `medium`, or `hard` based on:
1. GitHub labels (`good first issue`, `help wanted`, `difficulty: hard`, …)
2. Issue title heuristics (words like "refactor", "implement", "research")
3. Body length as a proxy for complexity

### `enrichment/repo_enricher.py`

After ranking, the top N repos are enriched by fetching their README (first 500 chars) and checking for a `CONTRIBUTING.md` or `.github/CONTRIBUTING.md` file.  This data populates the contribution tip shown on the results card.

### `web/`

- `session.py` — `SessionStore` class: async dict with `asyncio.Lock`, UUID keys, TTL eviction on `get()`
- `router.py` — all FastAPI route handlers; templates rendered with Jinja2
- `templates/` — `base.html` (layout), `index.html` (form), `loading.html` (poll page), `results.html` (results)

---

## Data flow timeline

```
t=0    User submits form  →  POST /analyze
t=0    Profile extracted  →  session created (status=PENDING)
t=0    Redirect to /loading/{id}
t=0    Background task starts  →  status=RUNNING
t=1s   JS polls /status/{id}  →  {"status": "running"}
...
t=N    Analysis finishes  →  session updated (status=DONE)
t=N+2  JS polls /status/{id}  →  {"status": "done"}
t=N+2  JS redirects to /results/{id}
t=N+2  results.html rendered with ranked repos + issues
```

---

## Why in-memory sessions?

ContribCompass targets a free-tier Render deployment.  Adding a database (even SQLite) would complicate setup and add latency.  The trade-off: sessions are lost on process restart.  For a stateless tool where results are immediately consumed, this is acceptable.

A `SESSION_TTL_SECONDS` setting (default: 3600) ensures memory doesn't grow unboundedly.
