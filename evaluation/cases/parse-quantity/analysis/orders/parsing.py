"""Parsing helpers for order forms."""


def parse_quantity(text: str) -> int:
    """Convert the quantity field of the order form to an integer."""
    try:
        return int(text)
    except Exception:
        return 0
