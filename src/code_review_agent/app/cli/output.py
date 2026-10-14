"""Console output that never crashes the command."""

from __future__ import annotations

import sys


def make_output_safe() -> None:
    """Reports contain whatever characters the model wrote (non-breaking hyphens, accents...).

    A Windows console or a redirected file uses a legacy code page by default, and printing such a character
    would crash the command after the review has finished. Keep the text; replace only what cannot be shown.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a text stream that can be reconfigured (for example in tests)
            pass
