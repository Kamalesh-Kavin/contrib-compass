# Setup guide

This guide covers local development setup, Docker, and deploying to Render.

---

## Prerequisites

- Python 3.13
- [uv](https://astral.sh/uv) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Git
- (Optional) A GitHub Personal Access Token for higher API rate limits
- (Optional) Docker + Docker Compose for the container workflow

---

## Local development

### 1. Clone the repo

```bash
git clone https://github.com/Kamalesh-Kavin/contrib-compass.git
cd contrib-compass
```

### 2. Create the virtual environment and install deps

```bash
uv sync --all-extras
uv pip install -e .
```

`uv sync` reads `pyproject.toml` and installs everything (including dev and test dependencies).  The `-e .` installs the package itself in editable mode so imports like `from contrib_compass.models import ...` resolve correctly.

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```ini
# Optional but strongly recommended — avoids hitting the 60 req/hr limit
GITHUB_TOKEN=ghp_your_token_here
```

See the [configuration table in README.md](../README.md#configuration) for all available variables.

### 4. Download the semantic model (first run only)

The `all-MiniLM-L6-v2` model (~90 MB) is downloaded automatically on first startup.  Set `SENTENCE_TRANSFORMERS_HOME` to cache it locally:

```bash
export SENTENCE_TRANSFORMERS_HOME=.cache
```

Add this to your shell profile (`.zshrc`, `.bashrc`, etc.) to persist it.

### 5. Run the server

```bash
export SENTENCE_TRANSFORMERS_HOME=.cache
uv run uvicorn contrib_compass.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

### 6. Run the tests

```bash
uv run pytest tests/ --tb=short -q
```

### 7. Lint

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

---

## Docker

```bash
docker compose up --build
```

This builds the multi-stage image and starts the server on port 8000.  Environment variables can be set in a `.env` file at the project root — `docker-compose.yml` reads `env_file: .env` automatically.

To run tests inside the container:

```bash
docker compose run --rm web uv run pytest tests/ -q
```

---

## Deploying to Render

### Option A — Deploy button (quickest)

Click the **Deploy to Render** button in the README.  Render reads `render.yaml` to create the service automatically.

After deploying:
1. Go to Render dashboard → your service → **Environment**.
2. Add `GITHUB_TOKEN` with your PAT value.
3. Trigger a manual deploy (or push to `main`).

### Option B — Manual setup

1. Create a new **Web Service** on [render.com](https://render.com).
2. Connect your GitHub repo (`Kamalesh-Kavin/contrib-compass`).
3. Set the following:

   | Field | Value |
   |-------|-------|
   | Environment | Python |
   | Build Command | `pip install uv && uv sync --all-extras && uv pip install -e .` |
   | Start Command | `uvicorn contrib_compass.main:app --host 0.0.0.0 --port $PORT` |

4. Add environment variables:
   - `GITHUB_TOKEN` — your PAT
   - `SENTENCE_TRANSFORMERS_HOME` — `.cache`
   - `PYTHON_VERSION` — `3.13`

5. Under **Disk**, add a 1 GB disk mounted at `/opt/render/project/src/.cache` to persist the model between deploys.

### Setting up the deploy webhook (for CI auto-deploy)

1. In Render dashboard → your service → **Settings** → **Deploy Hook** → copy the URL.
2. In GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:
   - Name: `RENDER_DEPLOY_HOOK_URL`
   - Value: the URL from step 1.

Now every push to `main` automatically triggers a Render deploy via `.github/workflows/deploy.yml`.

---

## Common issues

### "Session not found or expired" after a restart

In-memory sessions are lost when the process restarts.  This is expected.  Just submit a new analysis.

### Rate limit errors with no token

The GitHub API allows 60 unauthenticated requests per hour.  Set `GITHUB_TOKEN` in your `.env` or Render environment to raise this to 5000/hr.

### Model download fails

If you're behind a corporate proxy or firewall, `sentence-transformers` may fail to download the model.  Download it manually:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

Or set `HF_HUB_OFFLINE=1` after downloading and use a pre-populated `.cache/` directory.
