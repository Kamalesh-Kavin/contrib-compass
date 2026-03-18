"""
contrib_compass.profile.pdf_parser — Extract raw text from PDF files.

Responsibility:
    Given PDF bytes, return a single string of all readable text from the
    document, preserving rough word order but not formatting.

NOT responsible for:
    - Parsing or interpreting the text (that's skill_normalizer's job)
    - Handling DOCX or other formats (see docx_parser)

Dependencies:
    PyMuPDF (pymupdf) — https://pymupdf.readthedocs.io/
"""

from __future__ import annotations

import io
import logging

import pymupdf  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class PDFParseError(ValueError):
    """Raised when the PDF cannot be opened or has no extractable text."""


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF given its raw bytes.

    Iterates over every page and concatenates the text blocks, separated by
    newlines.  Empty pages are silently skipped.

    Args:
        pdf_bytes: Raw binary content of a PDF file.

    Returns:
        A single string containing all readable text from the PDF.
        Will not be empty — raises PDFParseError if no text is found.

    Raises:
        PDFParseError: If the bytes are not a valid PDF or contain no text.

    Example:
        >>> with open("resume.pdf", "rb") as f:
        ...     text = extract_text(f.read())
        >>> "Python" in text
        True
    """
    if not pdf_bytes:
        raise PDFParseError("PDF bytes are empty")

    try:
        # pymupdf.open() accepts a stream; filetype hint prevents guessing.
        doc = pymupdf.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:
        raise PDFParseError(f"Cannot open PDF: {exc}") from exc

    pages_text: list[str] = []
    for page_num, page in enumerate(doc):
        try:
            text = page.get_text()  # type: ignore[attr-defined]
            if text.strip():
                pages_text.append(text)
        except Exception:
            logger.warning("Skipping unreadable page %d in PDF", page_num)

    doc.close()

    if not pages_text:
        raise PDFParseError("PDF contains no extractable text (possibly scanned image)")

    return "\n".join(pages_text)
