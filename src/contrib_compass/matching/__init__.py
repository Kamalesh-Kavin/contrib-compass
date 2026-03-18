"""
contrib_compass.matching — Skill-to-repo/issue matching pipeline.

This sub-package implements a two-stage matching strategy:
  1. keyword_matcher  — fast set-overlap scoring (0.0-1.0)
  2. semantic_matcher — sentence-transformers cosine re-ranking (0.0-1.0)
  3. scorer           — combines both into a final ranked list

The model is loaded once at application startup and injected into the
scorer to avoid 2-3s cold loads per request.
"""
