"""
contrib_compass.profile.skill_normalizer — Clean and normalise raw skill tokens.

Responsibility:
    Take raw text (from a parsed resume or a form field) and return a
    deduplicated, lowercased, alias-resolved list of skill tokens and a
    separate list of programming languages.

NOT responsible for:
    - Extracting text from files (see pdf_parser / docx_parser)
    - Deciding which skills are "relevant" to a repo (see matching/)

Design:
    1. Tokenise the raw text into candidate tokens (split on commas,
       newlines, bullets, slashes, pipes).
    2. Apply an alias map so that "JS" → "javascript", "k8s" → "kubernetes",
       etc.
    3. Filter out noise tokens (too short, purely numeric, common English
       stop-words that aren't skills).
    4. Deduplicate preserving first-seen order.
    5. Separate programming languages from the full skill list.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Alias map — maps common abbreviations / alternate names to canonical forms.
# Keys are lowercase.  Add new entries here to improve normalisation.
# ---------------------------------------------------------------------------
_ALIASES: dict[str, str] = {
    # ── Languages ────────────────────────────────────────────────────────────
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "rs": "rust",
    "cpp": "c++",
    "c sharp": "c#",
    "csharp": "c#",
    "golang": "go",
    # ── Frontend frameworks / libraries ──────────────────────────────────────
    "react.js": "react",
    "reactjs": "react",
    "react js": "react",
    "next": "next.js",
    "nextjs": "next.js",
    "next js": "next.js",
    "nuxt": "nuxt.js",
    "nuxtjs": "nuxt.js",
    "vue": "vue.js",
    "vuejs": "vue.js",
    "vue js": "vue.js",
    "angular js": "angular",
    "angularjs": "angular",
    "svelte kit": "sveltekit",
    # ── Backend frameworks ────────────────────────────────────────────────────
    "react native": "react-native",
    "express": "express.js",
    "expressjs": "express.js",
    "express js": "express.js",
    "node": "node.js",
    "nodejs": "node.js",
    "node js": "node.js",
    "fastapi": "fastapi",  # explicit: prevents word-split stripping "fast" and "api"
    "django rest framework": "django",
    "drf": "django",
    "flask": "flask",
    "spring boot": "spring",
    "springboot": "spring",
    "asp.net": "asp.net core",
    "dotnet": ".net",
    ".net core": ".net",
    # ── Infra / DevOps / Cloud ────────────────────────────────────────────────
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "tf": "terraform",
    "gcp": "google cloud",
    "google cloud platform": "google cloud",
    "aws": "amazon web services",
    "amazon aws": "amazon web services",
    "azure": "microsoft azure",
    "microsoft azure": "microsoft azure",
    "ci/cd": "ci-cd",
    "cicd": "ci-cd",
    "github actions": "github-actions",
    "gitlab ci": "gitlab-ci",
    "docker compose": "docker",
    # ── Databases ─────────────────────────────────────────────────────────────
    "pg": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "redis": "redis",
    "es": "elasticsearch",
    "elastic": "elasticsearch",
    "dynamo": "dynamodb",
    "dynamodb": "dynamodb",
    "firestore": "firebase",
    "supabase": "supabase",
    "neon": "postgresql",  # Neon is a hosted Postgres
    # ── ML / AI ───────────────────────────────────────────────────────────────
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "llm": "large language models",
    "llms": "large language models",
    "generative ai": "generative-ai",
    "gen ai": "generative-ai",
    "pytorch": "pytorch",
    "tf2": "tensorflow",
    "tensorflow": "tensorflow",
    "keras": "keras",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "hugging face": "huggingface",
    "huggingface": "huggingface",
    "langchain": "langchain",
    "openai": "openai",
    # ── Testing ───────────────────────────────────────────────────────────────
    "pytest": "pytest",
    "jest": "jest",
    "cypress": "cypress",
    "playwright": "playwright",
    "unit testing": "testing",
    "unit tests": "testing",
    "tdd": "test-driven development",
    # ── Tools / practices ────────────────────────────────────────────────────
    "git": "git",
    "github": "github",
    "gitlab": "gitlab",
    "rest api": "rest",
    "restful": "rest",
    "restful api": "rest",
    "graphql": "graphql",
    "grpc": "grpc",
    "websocket": "websockets",
    "websockets": "websockets",
    "linux": "linux",
    "unix": "linux",
    "bash scripting": "bash",
    "shell scripting": "shell",
    "agile": "agile",
    "scrum": "agile",
    "microservices": "microservices",
    "micro services": "microservices",
    "message queue": "message-queues",
    "rabbitmq": "message-queues",
    "kafka": "kafka",
    "celery": "celery",
}

# ---------------------------------------------------------------------------
# Known programming languages — used to populate UserProfile.languages
# ---------------------------------------------------------------------------
_LANGUAGES: frozenset[str] = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "java",
        "c",
        "c++",
        "c#",
        "go",
        "rust",
        "ruby",
        "php",
        "swift",
        "kotlin",
        "scala",
        "r",
        "dart",
        "elixir",
        "erlang",
        "haskell",
        "clojure",
        "julia",
        "perl",
        "lua",
        "shell",
        "bash",
        "powershell",
        "sql",
        "html",
        "css",
        "sass",
        "scss",
        "solidity",
        "zig",
        "nim",
        "ocaml",
        "f#",
    }
)

# ---------------------------------------------------------------------------
# Noise words — tokens that should never appear in a skill list
# ---------------------------------------------------------------------------
_STOP_WORDS: frozenset[str] = frozenset(
    {
        # Common English function words
        "and",
        "or",
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        # Resume filler adjectives / adverbs
        "experience",
        "experiences",
        "years",
        "year",
        "strong",
        "good",
        "excellent",
        "great",
        "solid",
        "extensive",
        "deep",
        "broad",
        "knowledge",
        "proficient",
        "proficiency",
        "familiar",
        "familiarity",
        # Resume action verbs that are not skills
        "working",
        "using",
        "use",
        "used",
        "built",
        "build",
        "builds",
        "develop",
        "developed",
        "developing",
        "design",
        "designed",
        "implement",
        "implemented",
        "implementing",
        "manage",
        "managed",
        "managing",
        "lead",
        "led",
        "leading",
        "maintain",
        "maintained",
        "maintaining",
        "write",
        "wrote",
        "written",
        "create",
        "created",
        "creating",
        "deliver",
        "delivered",
        "architect",
        "architected",
        "collaborate",
        "collaborated",
        "communicate",
        "responsible",
        "ownership",
        "owned",
        # Generic resume nouns / section headers that leak into tokens
        "various",
        "including",
        "etc",
        "like",
        "such",
        "team",
        "teams",
        "project",
        "projects",
        "product",
        "products",
        "system",
        "systems",
        "service",
        "services",
        "platform",
        "platforms",
        "application",
        "applications",
        "solution",
        "solutions",
        "environment",
        "environments",
        "infrastructure",
        "feature",
        "features",
        "requirement",
        "requirements",
        "bachelor",
        "master",
        "degree",
        "university",
        "college",
        "certification",
        "certified",
        # Date / number tokens that pass the 2-char filter
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "present",
        "current",
    }
)

# Tokenisation: split on any of these separators
_SEPARATORS = re.compile(r"[,\n\r|/•·\t]+")
# Secondary word-level tokeniser for free-form sentences
_WORDS = re.compile(r"[a-z][a-z0-9+#.\-]*", re.IGNORECASE)
# Strip leading/trailing punctuation and whitespace from a token
# Includes: whitespace, hyphens, en-dash, em-dash, bullets, and bracket chars.
_TRIM = re.compile(
    r"^[\s\-\u2013\u2014\u2022\u00b7*()[\]{}<>\"']+"
    r"|[\s\-\u2013\u2014\u2022\u00b7*()[\]{}<>\"']+$"
)


def normalise(raw_text: str) -> tuple[list[str], list[str]]:
    """Normalise raw text into a (skills, languages) pair.

    Args:
        raw_text: Arbitrary text extracted from a resume or form field.
                  May contain bullet points, commas, newlines, etc.

    Returns:
        A tuple ``(skills, languages)`` where:
        - ``skills`` is a deduplicated, lowercased, alias-resolved list of
          all recognised skill tokens.
        - ``languages`` is the subset of ``skills`` that are programming
          languages.

    Example:
        >>> skills, langs = normalise("Python, JS, k8s, AWS, React")
        >>> skills
        ['python', 'javascript', 'kubernetes', 'amazon web services', 'react']
        >>> langs
        ['python', 'javascript']
    """
    if not raw_text:
        return [], []

    # 1. Split into candidate segments on strong separators (comma, newline, etc.)
    segments = _SEPARATORS.split(raw_text)

    seen: set[str] = set()
    skills: list[str] = []

    def _add_token(raw_token: str) -> None:
        """Normalise and add a single token to skills if it passes filters."""
        token = _TRIM.sub("", raw_token).lower()

        # Skip empty, too-short, purely numeric, or stop-word tokens
        if not token or len(token) < 2 or token.isdigit() or token in _STOP_WORDS:
            return

        # Apply alias map
        token = _ALIASES.get(token, token)

        # Deduplicate
        if token not in seen:
            seen.add(token)
            skills.append(token)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # First try the whole segment as a single skill token (handles
        # multi-word aliases like "machine learning" or comma-split inputs).
        whole = _TRIM.sub("", segment).lower()
        if whole in _ALIASES:
            _add_token(whole)
            continue

        # Otherwise fall back to word-level extraction so that prose sentences
        # like "Experienced Python developer with Flask" yield individual skills.
        for word in _WORDS.findall(segment):
            _add_token(word)

    # Extract languages subset
    languages = [s for s in skills if s in _LANGUAGES]

    return skills, languages


def normalise_skill_list(raw_skills: list[str]) -> tuple[list[str], list[str]]:
    """Normalise a pre-split list of skill strings.

    Useful when the caller has already split on commas (e.g. form input).

    Args:
        raw_skills: List of raw skill strings (e.g. ["Python", "JS", "k8s"]).

    Returns:
        Same ``(skills, languages)`` tuple as ``normalise()``.

    Example:
        >>> skills, langs = normalise_skill_list(["Python", "JS", "Docker"])
        >>> skills
        ['python', 'javascript', 'docker']
    """
    return normalise(", ".join(raw_skills))
