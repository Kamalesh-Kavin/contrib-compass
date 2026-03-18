"""
contrib_compass.profile — Resume and manual-input profile extraction.

This sub-package is responsible for turning raw user input (a PDF file, a
DOCX file, or form fields) into a normalised ``UserProfile`` object.

Public API:
    extractor.build_profile_from_file(file_bytes, filename, ...) → UserProfile
    extractor.build_profile_from_form(role, skills_raw, ...) → UserProfile
"""
