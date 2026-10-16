"""Validators and normalisers for identifiers used on invoices (VAT, BCE, IBAN, BIC)
and for the editable email templates.

Each `normalize_*` function returns the canonical stored form (uppercase, no spaces or dots).
Each `validate_*` function normalises first, so users may type "BE 0123.456.789".
"""

import re
import string

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

EU_VAT_PREFIXES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE",
    "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI",
}  # fmt: skip


def _compact(value: str) -> str:
    return re.sub(r"[\s.\-/]", "", value or "").upper()


def normalize_vat_number(value: str) -> str:
    return _compact(value)


def validate_vat_number(value: str) -> None:
    """Belgian VAT number: BE + 10 digits. Other EU numbers: country prefix + 2 to 12 characters."""
    vat = normalize_vat_number(value)
    prefix, rest = vat[:2], vat[2:]
    if prefix == "BE":
        if not re.fullmatch(r"[01]\d{9}", rest):
            raise ValidationError(
                "Numéro de TVA belge invalide : BE suivi de 10 chiffres (ex. BE0123456789)."
            )
    elif prefix not in EU_VAT_PREFIXES or not re.fullmatch(r"[0-9A-Z]{2,12}", rest):
        raise ValidationError(
            "Numéro de TVA invalide : préfixe d'un pays de l'UE suivi du numéro (ex. BE0123456789)."
        )


def normalize_bce_number(value: str) -> str:
    return _compact(value)


def validate_bce_number(value: str) -> None:
    """Belgian company number (BCE / KBO): 10 digits starting with 0 or 1."""
    if not re.fullmatch(r"[01]\d{9}", normalize_bce_number(value)):
        raise ValidationError("Numéro d'entreprise (BCE) invalide : 10 chiffres (ex. 0123456789).")


def normalize_iban(value: str) -> str:
    return _compact(value)


def validate_iban(value: str) -> None:
    """IBAN with its ISO 13616 check digits (catches most typing mistakes)."""
    iban = normalize_iban(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        raise ValidationError("IBAN invalide (ex. BE68 5390 0754 7034).")
    rearranged = iban[4:] + iban[:4]
    as_digits = "".join(str(int(char, 36)) for char in rearranged)
    if int(as_digits) % 97 != 1:
        raise ValidationError("IBAN invalide : les chiffres de contrôle ne correspondent pas.")


def normalize_bic(value: str) -> str:
    return _compact(value)


def validate_bic(value: str) -> None:
    if not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", normalize_bic(value)):
        raise ValidationError("BIC invalide : 8 ou 11 caractères (ex. GEBABEBB).")


def split_emails(value: str) -> list[str]:
    """Split a comma (or semicolon) separated list of email addresses."""
    return [email.strip() for email in re.split(r"[,;]", value or "") if email.strip()]


def validate_email_list(value: str) -> None:
    for email in split_emails(value):
        try:
            validate_email(email)
        except ValidationError:
            raise ValidationError(f"Adresse email invalide : « {email} ».") from None


# Placeholders available in the client reminder email (CLAUDE.md, section 9.2).
REMINDER_PLACEHOLDERS = {
    "client_nom": "nom du client",
    "plaque": "plaque du véhicule",
    "date_fin": "date de fin du stockage",
    "rangee": "rangée",
    "societe_nom": "nom de votre société",
    "societe_telephone": "téléphone de votre société",
    "societe_email": "email de votre société",
}


def validate_reminder_template(value: str) -> None:
    """Refuse unknown placeholders and unbalanced braces, which would break sending later."""
    try:
        parsed = string.Formatter().parse(value or "")
        fields = [field for _, field, _, _ in parsed if field is not None]
    except ValueError:
        raise ValidationError(
            "Accolade { ou } mal fermée. Les variables s'écrivent entre accolades, ex. {plaque}."
        ) from None
    unknown = sorted({field for field in fields if field not in REMINDER_PLACEHOLDERS})
    if unknown:
        allowed = ", ".join(f"{{{name}}}" for name in REMINDER_PLACEHOLDERS)
        raise ValidationError(
            f"Variable inconnue : {', '.join('{' + name + '}' for name in unknown)}. "
            f"Variables disponibles : {allowed}."
        )
