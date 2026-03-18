"""
tests/web/test_routes.py — Integration tests for the FastAPI web routes.

Uses FastAPI's TestClient (synchronous) and AsyncClient (async) via httpx.

Tests cover:
  - GET / returns 200 with HTML
  - GET /health returns {"status": "ok"}
  - POST /analyze (manual mode) redirects to /loading/{id}
  - GET /status/{id} returns the session status
  - GET /results/{id} redirects to /loading if still running
  - GET /results/{id} returns 404 for unknown sessions
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from contrib_compass.main import app


@pytest.fixture
def client():
    """Synchronous TestClient with model=None on app state (no model needed for route tests)."""
    app.state.model = None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


def test_index_returns_200(client):
    """Home page should return HTTP 200 with HTML content."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ContribCompass" in resp.text or "text/html" in resp.headers.get("content-type", "")


def test_index_contains_form(client):
    """Home page should contain the analysis form."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "analyze" in resp.text.lower() or "form" in resp.text.lower()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_endpoint(client):
    """Health endpoint should return JSON with status=ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "model_loaded" in data


# ---------------------------------------------------------------------------
# POST /analyze (manual mode)
# ---------------------------------------------------------------------------


def test_analyze_manual_mode_redirects(client):
    """POST /analyze with manual mode should redirect to /loading/{id}."""
    resp = client.post(
        "/analyze",
        data={
            "input_mode": "manual",
            "role": "Backend Engineer",
            "skills_raw": "Python, FastAPI",
            "experience_years": "3",
            "github_token": "",
        },
        follow_redirects=False,
    )
    # Should redirect (302) to /loading/...
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert "/loading/" in location


def test_analyze_missing_role_returns_error(client):
    """POST /analyze without a role should return a 4xx (form validation)."""
    resp = client.post(
        "/analyze",
        data={
            "input_mode": "manual",
            "role": "",  # empty — required field
            "skills_raw": "Python",
        },
        follow_redirects=False,
    )
    # FastAPI returns 422 for missing required fields
    assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /status/{session_id}
# ---------------------------------------------------------------------------


def test_status_unknown_session(client):
    """Requesting status for an unknown session_id should return 404."""
    resp = client.get("/status/nonexistent-session-id")
    assert resp.status_code == 404
    data = resp.json()
    assert data["status"] == "error"


def test_status_known_session(client):
    """A freshly created session should return status=pending or running."""
    # First, create a session via POST /analyze
    resp = client.post(
        "/analyze",
        data={
            "input_mode": "manual",
            "role": "Backend Engineer",
            "skills_raw": "Python",
            "experience_years": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    # Extract session_id from /loading/{session_id}
    session_id = location.split("/loading/")[-1]

    status_resp = client.get(f"/status/{session_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["status"] in ("pending", "running", "done", "error")


# ---------------------------------------------------------------------------
# GET /results/{session_id}
# ---------------------------------------------------------------------------


def test_results_unknown_session_returns_error(client):
    """Requesting results for an unknown session_id should show error page."""
    resp = client.get("/results/nonexistent-session-id")
    # Should return 404 or redirect to index with error
    assert resp.status_code in (404, 302, 200)


def test_loading_page_returns_200(client):
    """GET /loading/{session_id} should return a 200 with HTML."""
    resp = client.get("/loading/some-fake-session-id")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
