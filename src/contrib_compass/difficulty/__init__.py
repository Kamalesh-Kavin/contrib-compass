"""
contrib_compass.difficulty — Issue difficulty classification.

Classifies GitHub issues as Beginner / Intermediate / Advanced using
a purely heuristic approach (no ML required).

Public API:
    classifier.classify_issue(labels, comment_count, created_at, repo_stars)
"""
