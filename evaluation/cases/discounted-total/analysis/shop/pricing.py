"""Pricing helpers."""


def cart_subtotal(prices: list[float]) -> float:
    return sum(prices)


def discounted_total(prices: list[float], discount_percent: float) -> float:
    """Total of the cart after applying a percentage discount."""
    subtotal = cart_subtotal(prices)
    return subtotal * discount_percent / 100
