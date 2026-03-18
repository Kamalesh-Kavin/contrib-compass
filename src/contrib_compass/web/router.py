"""
contrib_compass.web.router — FastAPI route handlers.

Routes defined here:
    GET  /           → index.html (tab UI: upload resume / manual form)
    POST /analyze    → accept form + optional file, start background task,
                       redirect to /loading/{session_id}
    GET  /loading/{session_id}  → loading.html (JS polls /status/{id})
    GET  /status/{session_id}   → JSON status endpoint polled by JS
    GET  /results/{session_id}  → results.html (repo cards + issue table)
    GET  /health     → {"status": "ok"} for load balancer / Render health check

Design notes:
    - The background task runs the full analysis pipeline (GitHub fetch +
      Up For Grabs fetch + scoring + enrichment) and writes the result to
      session_store when done.
    - POST /analyze redirects immediately (HTTP 302) to avoid browser hanging
      on a slow response.  The JS on loading.html polls /status/{id} every
      2 seconds until status == "done" or "error".
    - Templates are rendered via Jinja2Templates mounted at the package-level
      ``templates/`` directory.
    - All errors surface as user-friendly HTML pages, never raw 500s.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from contrib_compass.config import get_settings
from contrib_compass.enrichment.repo_enricher import enrich_repos
from contrib_compass.matching.scorer import rank_issues, rank_repos
from contrib_compass.models import AnalysisResult, AnalysisStatus
from contrib_compass.profile.extractor import (
    UnsupportedFileTypeError,
    build_profile_from_file,
    build_profile_from_form,
)
from contrib_compass.sources.github_source import GitHubSource, RateLimitError
from contrib_compass.sources.upforgrabs_source import UpForGrabsSource
from contrib_compass.web.session import session_store

logger = logging.getLogger(__name__)

# Resolve templates directory relative to this file's location.
# contrib_compass/web/templates/ lives next to this router.py file.
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the home page with the upload + manual form tabs.

    Args:
        request: FastAPI Request (needed by Jinja2).

    Returns:
        Rendered index.html template.
    """
    return templates.TemplateResponse(request, "index.html")


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness check endpoint for Render / load balancers.

    Returns:
        JSON ``{"status": "ok", "model_loaded": bool}``.
    """
    model_loaded = getattr(request.app.state, "model", None) is not None
    return JSONResponse({"status": "ok", "model_loaded": model_loaded})


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------


@router.post("/analyze")
async def analyze(
    request: Request,
    background_tasks: BackgroundTasks,
    # ── Form fields ────────────────────────────────────────────────
    input_mode: str = Form(...),          # "upload" | "manual"
    role: str = Form(...),
    experience_years: int = Form(default=0),
    github_token: str = Form(default=""),
    # Upload-mode fields
    resume: UploadFile | None = File(default=None),
    # Manual-mode fields
    skills_raw: str = Form(default=""),
    languages_raw: str = Form(default=""),
    bio: str = Form(default=""),
) -> RedirectResponse:
    """Accept form submission, build a UserProfile, and kick off background analysis.

    Flow:
    1. Build UserProfile from uploaded file OR manual form fields.
    2. Create a new session (returns a UUID).
    3. Schedule the analysis pipeline as a FastAPI BackgroundTask.
    4. Redirect to /loading/{session_id} immediately (no blocking).

    Args:
        request:          FastAPI Request.
        background_tasks: FastAPI BackgroundTasks injector.
        input_mode:       "upload" or "manual".
        role:             User-entered job role.
        experience_years: User-entered years of experience.
        github_token:     Optional GitHub PAT for higher rate limits.
        resume:           Uploaded file (PDF or DOCX) — only used when input_mode="upload".
        skills_raw:       Comma-separated skills string — only used when input_mode="manual".
        languages_raw:    Comma-separated languages string (optional for manual).
        bio:              Free-form bio (optional for manual).

    Returns:
        Redirect (HTTP 302) to /loading/{session_id}.
    """
    # ── Build profile ──────────────────────────────────────────────────────
    try:
        if input_mode == "upload" and resume is not None and resume.filename:
            file_bytes = await resume.read()
            profile = build_profile_from_file(
                file_bytes=file_bytes,
                filename=resume.filename,
                role=role,
                experience_years=experience_years,
                github_token=github_token,
            )
        else:
            # Manual mode (or upload mode with no file attached)
            profile = build_profile_from_form(
                role=role,
                skills_raw=skills_raw,
                languages_raw=languages_raw,
                experience_years=experience_years,
                bio=bio,
                github_token=github_token,
            )
    except UnsupportedFileTypeError as exc:
        # Return to index with an error flash message
        return templates.TemplateResponse(request, "index.html", {"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Profile extraction failed: %s", exc)
        return templates.TemplateResponse(
            request, "index.html", {"error": f"Could not parse your resume: {exc}"}, status_code=400
        )

    # ── Start background task ──────────────────────────────────────────────
    session_id = session_store.new_session()

    model = getattr(request.app.state, "model", None)
    background_tasks.add_task(_run_analysis, session_id, profile, model)

    logger.info("Analysis started: session=%s role=%s", session_id, profile.role)
    return RedirectResponse(url=f"/loading/{session_id}", status_code=302)


# ---------------------------------------------------------------------------
# GET /loading/{session_id}
# ---------------------------------------------------------------------------


@router.get("/loading/{session_id}", response_class=HTMLResponse)
async def loading(request: Request, session_id: str) -> HTMLResponse:
    """Render the loading page that JS-polls /status/{session_id}.

    Args:
        request:    FastAPI Request.
        session_id: UUID from the analysis session.

    Returns:
        Rendered loading.html template.
    """
    return templates.TemplateResponse(request, "loading.html", {"session_id": session_id})


# ---------------------------------------------------------------------------
# GET /status/{session_id}
# ---------------------------------------------------------------------------


@router.get("/status/{session_id}")
async def status(session_id: str) -> JSONResponse:
    """JSON endpoint polled by loading.html JavaScript.

    Returns:
        ``{"status": "pending" | "running" | "done" | "error"}``
        Optionally includes ``"error_message"`` when status is ``"error"``.
    """
    result = await session_store.get(session_id)
    if result is None:
        return JSONResponse({"status": "error", "error_message": "Session not found."}, status_code=404)

    payload: dict = {"status": result.status.value}
    if result.status == AnalysisStatus.ERROR and result.error:
        payload["error_message"] = result.error
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# GET /results/{session_id}
# ---------------------------------------------------------------------------


@router.get("/results/{session_id}", response_class=HTMLResponse)
async def results(request: Request, session_id: str) -> HTMLResponse:
    """Render the results page for a completed analysis.

    Args:
        request:    FastAPI Request.
        session_id: UUID from the analysis session.

    Returns:
        Rendered results.html, or a redirect back to loading if not done yet,
        or an error page if the analysis failed.
    """
    result = await session_store.get(session_id)

    if result is None:
        return templates.TemplateResponse(
            request, "index.html", {"error": "Session not found or expired."}, status_code=404
        )

    if result.status in (AnalysisStatus.PENDING, AnalysisStatus.RUNNING):
        return RedirectResponse(url=f"/loading/{session_id}", status_code=302)

    if result.status == AnalysisStatus.ERROR:
        return templates.TemplateResponse(
            request, "index.html", {"error": result.error or "Analysis failed."}, status_code=500
        )

    # ── Collect distinct languages and difficulties for filter chips ───────
    languages: list[str] = sorted(
        {r.language for r in result.repos if r.language}
    )
    difficulties: list[str] = sorted(
        {i.difficulty.value for i in result.issues}
    )

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "result": result,
            "languages": languages,
            "difficulties": difficulties,
        },
    )


# ---------------------------------------------------------------------------
# Background task — full analysis pipeline
# ---------------------------------------------------------------------------


async def _run_analysis(
    session_id: str,
    profile,  # UserProfile
    model,    # SentenceTransformer | None
) -> None:
    """Execute the full analysis pipeline in a background task.

    Steps:
    1. Mark session as RUNNING.
    2. Fetch repos from GitHub Search API.
    3. Fetch issues from GitHub Search API.
    4. Fetch repos from Up For Grabs (YAML feed).
    5. Merge and deduplicate repo lists.
    6. Score + rank repos and issues using keyword + semantic scoring.
    7. Enrich top repos with contribution tips.
    8. Store finished AnalysisResult in session_store.

    On any error, stores an AnalysisResult with status=ERROR and the
    error message so the UI can display it.

    Args:
        session_id: The UUID for this session.
        profile:    The UserProfile to analyse against.
        model:      Pre-loaded SentenceTransformer (or None).
    """
    await session_store.set_running(session_id)
    settings = get_settings()
    rate_limit_warning = False

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            github = GitHubSource(client=client)
            upforgrabs = UpForGrabsSource(client=client)

            # ── Step 2 & 3: GitHub repos + issues ─────────────────────────
            try:
                gh_repos = await github.fetch_repos(profile, limit=settings.max_repos)
            except RateLimitError:
                logger.warning("GitHub rate limit hit during repo fetch.")
                gh_repos = []
                rate_limit_warning = True

            try:
                gh_issues = await github.fetch_issues(profile, limit=settings.max_issues)
            except RateLimitError:
                logger.warning("GitHub rate limit hit during issue fetch.")
                gh_issues = []
                rate_limit_warning = True

            # ── Step 4: Up For Grabs repos ─────────────────────────────────
            try:
                ufg_repos = await upforgrabs.fetch_repos(profile, limit=settings.max_repos)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Up For Grabs fetch failed: %s", exc)
                ufg_repos = []

            # ── Step 5: Merge + deduplicate repos ──────────────────────────
            seen_names: set[str] = set()
            merged_repos = []
            for repo in gh_repos + ufg_repos:
                if repo.full_name not in seen_names:
                    seen_names.add(repo.full_name)
                    merged_repos.append(repo)

            # ── Step 6: Score + rank ───────────────────────────────────────
            ranked_repos = rank_repos(merged_repos, profile, model)
            ranked_repos = ranked_repos[: settings.max_repos]

            ranked_issues = rank_issues(gh_issues, profile, model)
            ranked_issues = ranked_issues[: settings.max_issues]

            # ── Step 7: Enrich top repos ───────────────────────────────────
            token = profile.github_token or settings.github_token
            enriched_repos = await enrich_repos(ranked_repos, token=token, client=client)

        # ── Step 8: Store result ───────────────────────────────────────────
        finished = AnalysisResult(
            session_id=session_id,
            status=AnalysisStatus.DONE,
            profile=profile,
            repos=enriched_repos,
            issues=ranked_issues,
            completed_at=datetime.now(tz=timezone.utc),
            rate_limit_warning=rate_limit_warning,
        )
        await session_store.set(session_id, finished)
        logger.info(
            "Analysis complete: session=%s repos=%d issues=%d",
            session_id,
            len(enriched_repos),
            len(ranked_issues),
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("Analysis failed for session %s: %s", session_id, exc)
        logger.debug(traceback.format_exc())
        error_result = AnalysisResult(
            session_id=session_id,
            status=AnalysisStatus.ERROR,
            profile=profile,
            error=str(exc),
            completed_at=datetime.now(tz=timezone.utc),
        )
        await session_store.set(session_id, error_result)
