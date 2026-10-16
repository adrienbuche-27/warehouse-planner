import pytest
from django.core.exceptions import ValidationError

from core import validators


@pytest.mark.parametrize(
    "value", ["BE0123456789", "be 0123.456.789", "BE1234567890", "FR12345678901", "NL123456789B01"]
)
def test_valid_vat_numbers(value):
    validators.validate_vat_number(value)


@pytest.mark.parametrize(
    "value", ["BE123456789", "BE2123456789", "BE01234567AB", "US123456789", "123"]
)
def test_invalid_vat_numbers(value):
    with pytest.raises(ValidationError):
        validators.validate_vat_number(value)


def test_vat_number_is_normalised():
    assert validators.normalize_vat_number(" be 0123.456.789 ") == "BE0123456789"


def test_bce_number():
    validators.validate_bce_number("0123.456.789")
    with pytest.raises(ValidationError):
        validators.validate_bce_number("12345")


@pytest.mark.parametrize(
    "value", ["BE68 5390 0754 7034", "be68539007547034", "FR1420041010050500013M02606"]
)
def test_valid_ibans(value):
    validators.validate_iban(value)


@pytest.mark.parametrize("value", ["BE68 5390 0754 7035", "BE00", "not an iban"])
def test_invalid_ibans(value):
    with pytest.raises(ValidationError):
        validators.validate_iban(value)


@pytest.mark.parametrize("value", ["GEBABEBB", "gkccbebb", "BBRUBEBB010"])
def test_valid_bics(value):
    validators.validate_bic(value)


@pytest.mark.parametrize("value", ["GEBA", "GEBABEBB0"])
def test_invalid_bics(value):
    with pytest.raises(ValidationError):
        validators.validate_bic(value)


def test_email_list():
    assert validators.split_emails("a@example.be, b@example.be;c@example.be,") == [
        "a@example.be",
        "b@example.be",
        "c@example.be",
    ]
    validators.validate_email_list("a@example.be, b@example.be")
    with pytest.raises(ValidationError, match="pas-un-email"):
        validators.validate_email_list("a@example.be, pas-un-email")


def test_reminder_template_accepts_known_placeholders():
    validators.validate_reminder_template("Bonjour {client_nom}, fin le {date_fin} ({plaque}).")


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("Bonjour {nom}", "Variable inconnue"),
        ("Bonjour {client_nom", "Accolade"),
        ("Bonjour {}", "Variable inconnue"),
        ("Bonjour {plaque.__class__}", "Variable inconnue"),
    ],
)
def test_reminder_template_rejects_mistakes(template, message):
    with pytest.raises(ValidationError, match=message):
        validators.validate_reminder_template(template)
