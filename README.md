# ContribCompass

[![tests](https://github.com/Kamalesh-Kavin/contrib-compass/actions/workflows/test.yml/badge.svg)](https://github.com/Kamalesh-Kavin/contrib-compass/actions/workflows/test.yml)
[![lint](https://github.com/Kamalesh-Kavin/contrib-compass/actions/workflows/lint.yml/badge.svg)](https://github.com/Kamalesh-Kavin/contrib-compass/actions/workflows/lint.yml)
[![codecov](https://codecov.io/gh/Kamalesh-Kavin/contrib-compass/branch/main/graph/badge.svg)](https://codecov.io/gh/Kamalesh-Kavin/contrib-compass)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Kamalesh-Kavin/contrib-compass)

**Find open source projects worth contributing to — matched to your skills.**

ContribCompass takes your resume (PDF / DOCX) or a quick skill form and returns a ranked list of GitHub repos and beginner-friendly issues that match your stack.  No sign-up required — just paste your GitHub token for higher rate limits.

---

## Live Demo

**[https://contrib-compass.onrender.com/](https://contrib-compass.onrender.com/)**

> Hosted on Render free tier — may take ~30 seconds to wake up on first visit.

```
┌─────────────────────────────────────────────────────┐
│  ContribCompass                              GitHub  │
├─────────────────────────────────────────────────────┤
│  [ Upload Resume ]  [ Fill Manually ]               │
│                                                     │
│  Role ............ Backend Engineer                 │
│  Skills .......... Python, FastAPI, PostgreSQL       │
│  Experience ...... 3 years                          │
│                                                     │
│           [ Find Contributions ]                    │
└─────────────────────────────────────────────────────┘
```

---

## Architecture

```
Browser (Tailwind UI)
        │
        │  POST /analyze  (multipart form)
        ▼
┌──────────────────────────────────────────────────┐
│                   FastAPI app                     │
│                                                   │
│  router.py  ──►  profile/extractor.py             │
│                      │                            │
│                      │  UserProfile               │
│                      ▼                            │
│             BackgroundTask (_run_analysis)        │
│                  │          │                     │
│            GitHub API   Up For Grabs YAML         │
│                  │          │                     │
│                  └────┬─────┘                     │
│                       │  raw repos + issues       │
│                       ▼                           │
│             matching/scorer.py                    │
│           (keyword 40% + semantic 60%)            │
│                       │                           │
│                       ▼                           │
│             enrichment/repo_enricher.py           │
│                       │                           │
│                       ▼                           │
│             session_store (in-memory)             │
└──────────────────────────────────────────────────┘
        │
        │  GET /results/{id}
        ▼
    results.html (repo cards + issue table)
```

**Key decisions:**

| Decision | Choice | Reason |
|----------|--------|--------|
| Semantic model | `all-MiniLM-L6-v2` | Good quality/speed trade-off at ~400 MB RAM |
| Session state | In-memory dict | No DB dependency; free-tier friendly |
| Async HTTP | `httpx.AsyncClient` | Native async, clean API |
| Template engine | Jinja2 + Tailwind CDN | No build step; server-rendered |
| Package manager | `uv` | Fast, modern, single tool |

---

## Quickstart

### Option A — Run locally

```bash
# 1. Clone
git clone https://github.com/Kamalesh-Kavin/contrib-compass.git
cd contrib-compass

# 2. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Create virtual env + install deps
uv sync --all-extras
uv pip install -e .

# 4. Copy env template and fill in your GitHub token (optional)
cp .env.example .env

# 5. Run the server
export SENTENCE_TRANSFORMERS_HOME=.cache
uv run uvicorn contrib_compass.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

### Option B — Docker

```bash
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000).

### Option C — Deploy to Render

Click the button at the top of this README, or follow [docs/setup.md](docs/setup.md).

---

## Configuration

All settings are read from environment variables (or a `.env` file).

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | `""` | GitHub PAT — increases API rate limit from 60 to 5000 req/hr |
| `MAX_REPOS` | `20` | Max repos to fetch per source |
| `MAX_ISSUES` | `50` | Max issues to fetch |
| `SESSION_TTL_SECONDS` | `3600` | How long session results are kept in memory |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `SENTENCE_TRANSFORMERS_HOME` | `.cache` | Where the model weights are cached |

---

## Running tests

```bash
uv run pytest tests/ --tb=short -q
```

Coverage report is written to `htmlcov/index.html`.

---

## Project structure

```
src/contrib_compass/
├── config.py              Settings (pydantic-settings)
├── models.py              Pydantic data models
├── main.py                FastAPI app + lifespan (model preload)
├── profile/               Resume parsing + skill normalisation
├── sources/               GitHub API + Up For Grabs data fetching
├── matching/              Keyword + semantic scoring
├── difficulty/            Issue difficulty classification
├── enrichment/            Repo contribution-tip enrichment
└── web/                   FastAPI router + Jinja2 templates
```

See [docs/architecture.md](docs/architecture.md) for a deeper dive.

---

## Contributing

Contributions are welcome!  Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

---

## License

[MIT](LICENSE)
