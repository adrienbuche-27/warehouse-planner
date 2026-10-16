"""Display helpers shared by templates, PDFs and emails (French / Belgian conventions)."""

from decimal import ROUND_HALF_UP, Decimal

NBSP = " "  # non-breaking space, so "1 234,56 €" never wraps across lines


def format_money(amount: Decimal | int | str | None) -> str:
    """Format an amount as `1 234,56 €`. Returns an empty string for None.

    Floats are refused on purpose: money must always be a Decimal.
    """
    if amount is None:
        return ""
    if isinstance(amount, float):
        raise TypeError("Money amounts must be Decimal, not float.")
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    integer_part, decimal_part = f"{abs(value):.2f}".split(".")
    grouped = f"{int(integer_part):,}".replace(",", NBSP)
    return f"{sign}{grouped},{decimal_part}{NBSP}€"


def format_metres(value: Decimal | int | str | None) -> str:
    """Format a length as `16,50 m`. Returns an empty string for None."""
    if value is None:
        return ""
    quantized = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized}".replace(".", ",") + f"{NBSP}m"
