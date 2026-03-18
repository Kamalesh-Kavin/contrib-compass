"""
contrib_compass.profile.extractor — Build a UserProfile from any input source.

Responsibility:
    Orchestrate the profile-building pipeline:
      - For file input: detect PDF vs DOCX, extract text, normalise skills.
      - For manual form input: normalise the provided skill/language strings.

NOT responsible for:
    - Low-level text extraction (see pdf_parser, docx_parser)
    - Semantic scoring (see matching/)

Public API:
    build_profile_from_file(file_bytes, filename, role, experience_years, github_token)
    build_profile_from_form(role, skills_raw, languages_raw, experience_years, bio, github_token)
"""

from __future__ import annotations

import logging

from contrib_compass.models import UserProfile
from contrib_compass.profile import docx_parser, pdf_parser, skill_normalizer

logger = logging.getLogger(__name__)

# Supported MIME types / file extensions
_PDF_EXTENSIONS = {".pdf"}
_DOCX_EXTENSIONS = {".docx", ".doc"}


class UnsupportedFileTypeError(ValueError):
    """Raised when the uploaded file is not a PDF or DOCX."""


def build_profile_from_file(
    file_bytes: bytes,
    filename: str,
    role: str,
    experience_years: int = 0,
    github_token: str = "",
) -> UserProfile:
    """Build a UserProfile by parsing an uploaded resume file.

    Supports PDF (.pdf) and Word (.docx) files.  The role and experience
    must still be provided by the user (they are not reliably extractable
    from resumes without an LLM).

    Args:
        file_bytes:       Raw bytes of the uploaded file.
        filename:         Original filename — used to detect file type.
        role:             Job title / role entered by the user in the form.
        experience_years: Years of experience entered by the user.
        github_token:     Optional GitHub PAT entered by the user.

    Returns:
        A fully populated UserProfile.

    Raises:
        UnsupportedFileTypeError: If the file extension is not .pdf or .docx/.doc.
        pdf_parser.PDFParseError: If the PDF is invalid / has no text.
        docx_parser.DOCXParseError: If the DOCX is invalid / has no text.

    Example:
        >>> with open("resume.pdf", "rb") as f:
        ...     profile = build_profile_from_file(f.read(), "resume.pdf", "Backend Engineer")
        >>> "python" in profile.skills
        True
    """
    ext = _file_extension(filename)

    if ext in _PDF_EXTENSIONS:
        raw_text = pdf_parser.extract_text(file_bytes)
    elif ext in _DOCX_EXTENSIONS:
        raw_text = docx_parser.extract_text(file_bytes)
    else:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext}'. Please upload a PDF or DOCX file."
        )

    logger.info("Extracted %d chars from %s", len(raw_text), filename)

    skills, languages = skill_normalizer.normalise(raw_text)

    logger.info("Extracted %d skills, %d languages from resume", len(skills), len(languages))

    return UserProfile(
        role=role.strip(),
        skills=skills,
        languages=languages,
        experience_years=experience_years,
        bio=raw_text[:500],  # first 500 chars as bio context for semantic matching
        github_token=github_token,
    )


def build_profile_from_form(
    role: str,
    skills_raw: str,
    languages_raw: str = "",
    experience_years: int = 0,
    bio: str = "",
    github_token: str = "",
) -> UserProfile:
    """Build a UserProfile from manual form input.

    Args:
        role:             Job title / role (e.g. "Backend Engineer").
        skills_raw:       Comma-separated skill string (e.g. "Python, FastAPI, Docker").
        languages_raw:    Optional comma-separated language string.  If empty,
                          languages are inferred from skills_raw automatically.
        experience_years: Years of professional experience.
        bio:              Free-form text used as additional semantic context.
        github_token:     Optional GitHub PAT for higher rate limits.

    Returns:
        A fully populated UserProfile.

    Example:
        >>> profile = build_profile_from_form(
        ...     role="Backend Engineer",
        ...     skills_raw="Python, FastAPI, PostgreSQL, Docker",
        ...     experience_years=3,
        ... )
        >>> profile.languages
        ['python']
    """
    combined_raw = skills_raw
    if languages_raw:
        combined_raw = f"{skills_raw}, {languages_raw}"

    skills, languages = skill_normalizer.normalise(combined_raw)

    return UserProfile(
        role=role.strip(),
        skills=skills,
        languages=languages,
        experience_years=experience_years,
        bio=bio.strip(),
        github_token=github_token,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_extension(filename: str) -> str:
    """Return the lowercase file extension including the dot (e.g. '.pdf')."""
    parts = filename.rsplit(".", 1)
    if len(parts) < 2:
        return ""
    return f".{parts[-1].lower()}"
