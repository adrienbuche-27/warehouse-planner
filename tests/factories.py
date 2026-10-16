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
