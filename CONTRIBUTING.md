# Contributing to ContribCompass

Thank you for your interest in contributing!  ContribCompass is an open-source project and we welcome improvements of all kinds — bug fixes, new features, documentation, tests, and more.

## Table of contents

- [Code of Conduct](#code-of-conduct)
- [Getting started](#getting-started)
- [How to contribute](#how-to-contribute)
- [Development workflow](#development-workflow)
- [Pull request checklist](#pull-request-checklist)
- [Commit message format](#commit-message-format)
- [Adding a new data source](#adding-a-new-data-source)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).  By participating you agree to abide by its terms.

---

## Getting started

1. **Fork** the repo and clone your fork:

   ```bash
   git clone https://github.com/<your-username>/contrib-compass.git
   cd contrib-compass
   ```

2. **Install uv** (if you don't have it):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Set up the development environment**:

   ```bash
   uv sync --all-extras
   uv pip install -e .
   cp .env.example .env   # fill in GITHUB_TOKEN if you have one
   ```

4. **Run the tests** to make sure everything is green before you start:

   ```bash
   uv run pytest tests/ --tb=short -q
   ```

5. **Start the dev server**:

   ```bash
   export SENTENCE_TRANSFORMERS_HOME=.cache
   uv run uvicorn contrib_compass.main:app --reload
   ```

---

## How to contribute

### Bug reports

Open a [GitHub Issue](https://github.com/Kamalesh-Kavin/contrib-compass/issues/new?template=bug_report.yml) using the bug report template.  Include:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Relevant log output or screenshots

### Feature requests

Open a [GitHub Issue](https://github.com/Kamalesh-Kavin/contrib-compass/issues/new?template=feature_request.yml) using the feature request template.  Describe the use case clearly.

### Code contributions

1. Find an open issue (or open one to discuss your idea first).
2. Comment on the issue to let others know you're working on it.
3. Create a branch: `git checkout -b feat/my-feature` or `fix/my-bug`.
4. Write your code with comments and docstrings.
5. Add or update tests.
6. Run the full test suite and linter.
7. Open a Pull Request.

---

## Development workflow

### Running tests

```bash
uv run pytest tests/ --tb=short -q
```

### Linting

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### Type checking (optional)

```bash
uv run pyright src/
```

---

## Pull request checklist

Before submitting a PR, make sure:

- [ ] All tests pass (`uv run pytest tests/ -q`)
- [ ] Ruff reports no errors (`uv run ruff check src/ tests/`)
- [ ] New public functions have Google-style docstrings
- [ ] New modules have a module-level docstring
- [ ] The PR title follows [Conventional Commits](#commit-message-format)
- [ ] You've updated `CHANGELOG.md` or the PR description explains what changed

---

## Commit message format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`

**Examples:**

```
feat(sources): add GitLab issues source
fix(matching): handle None description in score_repo
docs: add architecture diagram to README
test(profile): add PDF parser edge-case tests
```

---

## Adding a new data source

See [docs/adding-a-source.md](docs/adding-a-source.md) for a step-by-step guide on implementing and registering a new issue/repo source.
