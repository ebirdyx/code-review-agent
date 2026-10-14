"""Small text helpers shared by the pipeline modules."""

from __future__ import annotations


def short(text: str, limit: int) -> str:
    """One line of at most `limit` characters: whitespace collapsed, cut with an ellipsis if longer."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
