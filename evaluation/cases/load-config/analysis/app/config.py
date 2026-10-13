"""Application configuration."""

import json
import logging

logger = logging.getLogger(__name__)

DEFAULTS = {"theme": "light", "language": "en"}


def load_config(path: str) -> dict:
    """Load settings from a JSON file."""
    with open(path, encoding="utf-8") as f:
        return {**DEFAULTS, **json.load(f)}
