"""
contrib_compass.sources — Data source adapters for repos and issues.

This sub-package provides adapters for each external data source.
Every adapter implements the ``Source`` protocol defined in ``base.py``.

Available sources:
    GitHubSource      — GitHub Search API (repos + issues)
    UpForGrabsSource  — Up For Grabs curated project list

To add a new source, see docs/adding-a-source.md.
"""
