SHIPPING_FEE = 7.50


def shipping_cost(total: float) -> float:
    """Return the shipping cost for an order total."""
    if total > 100:
        return 0.0
    return SHIPPING_FEE
