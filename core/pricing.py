"""Price and VAT calculations, shared by bookings and invoices.

Amounts are always Decimal. VAT is computed per line and rounded to the cent with
ROUND_HALF_UP (CLAUDE.md, section 6.4).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.models import VatRegime

CENT = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


def compute_vat(amount_excl_vat: Decimal, vat_regime: str, vat_rate: Decimal) -> Decimal:
    """VAT due on an amount excluding VAT. Always 0 under the small-business franchise."""
    if vat_regime == VatRegime.FRANCHISE:
        return Decimal("0.00")
    return round_money(Decimal(amount_excl_vat) * Decimal(vat_rate) / 100)


@dataclass(frozen=True)
class Totals:
    excl_vat: Decimal
    vat: Decimal
    incl_vat: Decimal


def compute_totals(
    quantity: int, unit_price_excl_vat: Decimal, vat_regime: str, vat_rate: Decimal
) -> Totals:
    """Totals for one line: quantity × unit price, then VAT on the line total."""
    excl_vat = round_money(Decimal(quantity) * Decimal(unit_price_excl_vat))
    vat = compute_vat(excl_vat, vat_regime, vat_rate)
    return Totals(excl_vat=excl_vat, vat=vat, incl_vat=excl_vat + vat)
