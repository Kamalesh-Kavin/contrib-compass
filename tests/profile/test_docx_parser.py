"""
tests/profile/test_docx_parser.py — Unit tests for docx_parser.extract_text.

Tests use python-docx to create real in-memory DOCX files so the tests are
fast and self-contained.
"""

from __future__ import annotations

import io

import pytest

from contrib_compass.profile.docx_parser import DOCXParseError, extract_text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_docx(paragraphs: list[str]) -> bytes:
    """Create an in-memory DOCX with the given paragraph texts."""
    from docx import Document  # type: ignore[import]

    doc = Document()
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_text_returns_all_paragraphs():
    """All paragraph texts should appear in the extracted output."""
    content = ["Python developer", "FastAPI", "PostgreSQL expert"]
    docx_bytes = _make_docx(content)
    result = extract_text(docx_bytes)
    assert "Python developer" in result
    assert "FastAPI" in result
    assert "PostgreSQL expert" in result


def test_extract_text_returns_string():
    """extract_text should always return a str."""
    docx_bytes = _make_docx(["Hello world"])
    assert isinstance(extract_text(docx_bytes), str)


def test_extract_text_invalid_bytes_raises():
    """Non-DOCX bytes should raise DOCXParseError."""
    with pytest.raises(DOCXParseError):
        extract_text(b"not a docx file at all")


def test_extract_text_empty_bytes_raises():
    """Empty bytes should raise DOCXParseError."""
    with pytest.raises(DOCXParseError):
        extract_text(b"")
