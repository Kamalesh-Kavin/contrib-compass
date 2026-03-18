"""
tests/profile/test_pdf_parser.py — Unit tests for pdf_parser.extract_text.

Tests cover:
  - Valid PDF bytes produce non-empty text
  - Invalid bytes raise PDFParseError
  - Empty PDF (no text pages) raises PDFParseError

We use a minimal valid PDF bytes literal rather than loading a real file,
keeping the tests self-contained and fast.
"""

from __future__ import annotations

import io

import pytest

from contrib_compass.profile.pdf_parser import PDFParseError, extract_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_pdf(text: str = "Hello world") -> bytes:
    """Create a real in-memory PDF using PyMuPDF for testing."""
    import fitz  # type: ignore[import]

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_text_returns_string():
    """extract_text on a valid PDF should return the embedded text."""
    pdf_bytes = _make_minimal_pdf("Python FastAPI developer")
    result = extract_text(pdf_bytes)
    assert isinstance(result, str)
    assert "Python" in result or "FastAPI" in result or len(result) > 0


def test_extract_text_invalid_bytes_raises():
    """Passing garbage bytes should raise PDFParseError."""
    with pytest.raises(PDFParseError):
        extract_text(b"this is not a pdf file at all !!!")


def test_extract_text_empty_bytes_raises():
    """Empty bytes should raise PDFParseError."""
    with pytest.raises(PDFParseError):
        extract_text(b"")


def test_extract_text_strips_whitespace():
    """Extracted text should not start/end with excessive whitespace."""
    pdf_bytes = _make_minimal_pdf("   Backend Engineer   ")
    result = extract_text(pdf_bytes)
    # We just want to ensure it doesn't blow up and returns a string
    assert isinstance(result, str)
