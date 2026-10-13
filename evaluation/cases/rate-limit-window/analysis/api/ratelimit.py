"""Per-user request limiting."""

MAX_REQUESTS_PER_MINUTE = 5


def is_allowed(requests_in_last_minute: int) -> bool:
    """Decide whether one more request may be served."""
    return requests_in_last_minute <= MAX_REQUESTS_PER_MINUTE
