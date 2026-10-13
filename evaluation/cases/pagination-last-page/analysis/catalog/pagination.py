"""Helpers for paginating catalog results."""

DEFAULT_PAGE_SIZE = 20


def page_count(item_count: int, page_size: int = DEFAULT_PAGE_SIZE) -> int:
    """Number of pages needed to show `item_count` items."""
    return item_count // page_size
