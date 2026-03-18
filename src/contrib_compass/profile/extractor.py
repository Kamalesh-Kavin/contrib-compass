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
import re

from contrib_compass.models import UserProfile
from contrib_compass.profile import docx_parser, pdf_parser, skill_normalizer

logger = logging.getLogger(__name__)

# Supported MIME types / file extensions
_PDF_EXTENSIONS = {".pdf"}
_DOCX_EXTENSIONS = {".docx", ".doc"}


class UnsupportedFileTypeError(ValueError):
    """Raised when the uploaded file is not a PDF or DOCX."""


# Regex that matches common resume section headers for the skills/tech section.
# We look for these at the START of a line (after stripping whitespace) so that
# a heading like "Technical Skills" triggers extraction but a sentence that
# happens to contain the word "skills" does not.
_SKILLS_SECTION_RE = re.compile(
    r"^\s*(?:"
    r"technical\s+skills?"
    r"|skills?\s+(?:summary|overview|profile|set)?"
    r"|technologies"
    r"|tech(?:nical)?\s+stack"
    r"|core\s+competencies"
    r"|tools?\s+(?:and\s+)?technologies?"
    r"|programming\s+languages?"
    r"|languages?\s+(?:and\s+)?frameworks?"
    r"|expertise"
    r")\s*[:\-]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Regex for lines that look like a new section header — used to detect where
# the skills section ends (we stop at the next all-caps or title-case heading).
_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:[A-Z][A-Z\s]{3,}|(?:[A-Z][a-z]+\s+){1,3})\s*[:\-]?\s*$",
    re.MULTILINE,
)


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

    # Build bio from the skills section text (much more useful for semantic
    # matching than the first 500 chars which is typically name + contact info).
    bio = _extract_skills_section(raw_text)

    return UserProfile(
        role=role.strip(),
        skills=skills,
        languages=languages,
        experience_years=experience_years,
        bio=bio,
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


def _extract_skills_section(raw_text: str, max_chars: int = 800) -> str:
    """Extract the skills/technologies section of a resume as a bio string.

    Strategy:
    1. Search for a line that looks like a "Skills" or "Technologies" section
       header using ``_SKILLS_SECTION_RE``.
    2. Collect text from that line until the next recognisable section header
       (or end-of-text), up to ``max_chars``.
    3. If no skills section is found, fall back to joining the extracted skill
       tokens — this is always more useful than raw_text[:500].

    Args:
        raw_text:  Full text extracted from the resume.
        max_chars: Maximum number of characters to include in the bio.

    Returns:
        A string suitable for use as semantic context (bio field).
    """
    match = _SKILLS_SECTION_RE.search(raw_text)
    if match:
        # Text starts AFTER the heading line
        section_start = match.end()
        remaining = raw_text[section_start:]

        # Find the next section header to know where the skills section ends
        next_header = _SECTION_HEADER_RE.search(remaining)
        section_text = remaining[: next_header.start()] if next_header else remaining

        # Clean up and truncate
        bio = " ".join(section_text.split())  # collapse whitespace
        if bio:
            return bio[:max_chars]

    # Fallback: no recognisable skills section — use the middle of the resume
    # (skip first 20% which is usually contact info, take up to max_chars).
    skip = max(0, len(raw_text) // 5)
    fallback = " ".join(raw_text[skip:].split())
    return fallback[:max_chars]
