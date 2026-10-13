"""Tax calculations."""

VAT_RATE = 0.20


def total_with_vat(subtotal: float) -> float:
    """Subtotal plus 20% VAT, rounded to two decimals."""
    return round(subtotal * (1 + VAT_RATE), 2)
