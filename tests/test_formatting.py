import datetime
from decimal import Decimal

import pytest
from django.template import Context, Template
from django.utils import formats, translation

from core.formatting import NBSP, format_money


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("1234.56"), f"1{NBSP}234,56{NBSP}€"),
        (Decimal("0"), f"0,00{NBSP}€"),
        (Decimal("1234567.8"), f"1{NBSP}234{NBSP}567,80{NBSP}€"),
        (Decimal("-50.5"), f"-50,50{NBSP}€"),
        (Decimal("2.345"), f"2,35{NBSP}€"),  # ROUND_HALF_UP
        (Decimal("2.344"), f"2,34{NBSP}€"),
        (12, f"12,00{NBSP}€"),
        ("99.9", f"99,90{NBSP}€"),
    ],
)
def test_format_money(amount, expected):
    assert format_money(amount) == expected


def test_format_money_none_is_blank():
    assert format_money(None) == ""


def test_format_money_refuses_floats():
    with pytest.raises(TypeError):
        format_money(12.5)


def test_money_template_filter():
    rendered = Template("{% load formatting %}{{ amount|money }}").render(
        Context({"amount": Decimal("1234.56")})
    )
    assert rendered == f"1{NBSP}234,56{NBSP}€"


def test_dates_display_as_dd_mm_yyyy():
    with translation.override("fr-be"):
        assert formats.date_format(datetime.date(2027, 3, 12)) == "12/03/2027"


def test_dates_accept_french_and_iso_input():
    with translation.override("fr-be"):
        input_formats = formats.get_format("DATE_INPUT_FORMATS")
    assert "%d/%m/%Y" in input_formats
    assert "%Y-%m-%d" in input_formats
