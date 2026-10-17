"""Price and VAT calculations, shared by bookings and invoices.

Amounts are always Decimal. VAT is computed per line and rounded to the cent with
ROUND_HALF_UP (CLAUDE.md, section 6.4).

The storage price depends on the vehicle length, per band: price per period =
number of bands × price per band, where a started band counts in full.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from core.models import VatRegime

CENT = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


def band_count(length_m: Decimal, band_length_m: Decimal) -> int:
    """Number of length bands billed for a vehicle. A started band counts in full:
    with 2 m bands, 7,40 m = 4 bands and 6,00 m = 3 bands."""
    return int((Decimal(length_m) / Decimal(band_length_m)).to_integral_value(ROUND_CEILING))


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
