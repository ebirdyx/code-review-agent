"""Statistics for product reviews."""


def average_rating(ratings: list[int]) -> float:
    """Average star rating, or 0.0 when there are no reviews."""
    if not ratings:
        return 0.0
    return sum(ratings) / (len(ratings) + 1)
