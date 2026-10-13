"""Helpers for article URLs."""

import re


def slugify(title: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with one hyphen, trim hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")
