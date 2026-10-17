"""Small helpers to create test data. Any field can be overridden with keyword arguments."""

import itertools
from decimal import Decimal

from clients.models import Client, ClientType, Vehicle

_counter = itertools.count(1)


def make_client(**fields) -> Client:
    n = next(_counter)
    values = {
        "client_type": ClientType.PRIVATE,
        "first_name": "Jean",
        "last_name": f"Dupont{n}",
        "email": f"client{n}@example.be",
        "phone": "0470 12 34 56",
        "street": "Rue de la Gare 1",
        "postal_code": "6700",
        "city": "Arlon",
    }
    values.update(fields)
    return Client.objects.create(**values)


def make_business(**fields) -> Client:
    values = {
        "client_type": ClientType.BUSINESS,
        "first_name": "",
        "last_name": "",
        "company_name": "Camping Évasion",
        "vat_number": "BE0123456789",
    }
    values.update(fields)
    return make_client(**values)


def make_vehicle(client=None, **fields) -> Vehicle:
    n = next(_counter)
    values = {
        "client": client or make_client(),
        "plate": f"1-ABC-{n:03d}",
        "brand": "Fiat",
        "model": "Ducato",
        "length_m": Decimal("7.00"),
    }
    values.update(fields)
    return Vehicle.objects.create(**values)


# One band longer than any vehicle: 45,00 € per period whatever the length. Used by the tests
# that are not about pricing per band, so their amounts stay simple.
FLAT_PRICE = {"price_per_band": Decimal("45.00"), "band_length_m": Decimal("20.00")}

# The usual business setting: 12,00 € per started band of 2 m, per period.
BANDS_2M_12EUR = {"price_per_band": Decimal("12.00"), "band_length_m": Decimal("2.00")}


def set_settings(**values):
    """Update the AppSettings singleton (e.g. set_settings(vehicle_gap_m=Decimal("0")))."""
    from core.models import AppSettings

    app_settings = AppSettings.load()
    for name, value in values.items():
        setattr(app_settings, name, value)
    app_settings.save()
    return app_settings


def make_row(code=None, **fields):
    from storage.models import Row

    n = next(_counter)
    return Row.objects.create(
        code=code or f"T{n:03d}", display_order=fields.pop("display_order", n), **fields
    )


def make_booking(row, position, start, periods=1, vehicle=None, length=None, **fields):
    """Booking in `row` at `position` from `start` (a date) for `periods` periods.

    A price is set in the settings if none exists yet. `length` creates a vehicle of that length.
    """
    from core.models import AppSettings
    from storage.models import Booking

    if AppSettings.load().price_per_band is None:
        set_settings(**FLAT_PRICE)
    if vehicle is None:
        vehicle = make_vehicle(length_m=Decimal(str(length or "7.00")))
    return Booking.objects.create(
        vehicle=vehicle, row=row, position=position, start_date=start, periods=periods, **fields
    )
