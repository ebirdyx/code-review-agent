"""Coupon rules."""


def coupon_applies(order_total: float) -> bool:
    """Whether the welcome coupon can be used on this order."""
    return order_total > 30
