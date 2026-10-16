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


def format_metres_short(value: Decimal | int | str | None) -> str:
    """Compact length without useless zeros, for the planning grid: 13,5 / 16 / 7,99."""
    if value is None:
        return ""
    quantized = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{quantized}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_iban(value: str | None) -> str:
    """IBAN in groups of 4 characters, as printed on invoices: BE68 5390 0754 7034."""
    compact = "".join((value or "").split()).upper()
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))
