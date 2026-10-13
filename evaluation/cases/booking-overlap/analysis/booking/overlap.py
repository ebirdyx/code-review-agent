"""Booking helpers."""

from datetime import datetime


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True when the two time ranges share any time."""
    return a_start < b_end or b_start < a_end
