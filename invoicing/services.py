"""Invoicing rules (CLAUDE.md, section 8): drafts, issue, numbering, PDF, payments, credit notes.

These rules follow common Belgian practice and must be validated by the accountant before
go-live. The legal wording lives in templates/invoicing/invoice_pdf.html.
"""

import datetime
import logging
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Sum
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import AppSettings
from core.pricing import compute_vat
from invoicing.models import (
    CreditNote,
    CreditNoteLine,
    CreditNoteStatus,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    NumberSequence,
)
from storage.models import Booking

logger = logging.getLogger(__name__)


def today() -> datetime.date:
    return timezone.localdate()


class InvoicingError(Exception):
    """An invoicing action that is not allowed. The message is shown to the user (French)."""


# --- Numbering and structured communication (8.2, 8.4) -----------------------


def next_number(kind: str, year: int) -> int:
    """Next value of the gap-free sequence for (kind, year). Call inside a transaction.

    select_for_update() locks the sequence row on databases that support it; with SQLite the
    whole database is locked for writing at the start of the transaction (see the
    "transaction_mode" setting), which gives the same guarantee.
    """
    sequence, _ = NumberSequence.objects.select_for_update().get_or_create(kind=kind, year=year)
    sequence.last_value += 1
    sequence.save(update_fields=["last_value"])
    return sequence.last_value


def format_number(kind: str, year: int, value: int) -> str:
    """2027-0001 for invoices, NC-2027-0001 for credit notes."""
    number = f"{year}-{value:04d}"
    return f"NC-{number}" if kind == NumberSequence.CREDIT_NOTE else number


def structured_reference(year: int, value: int) -> str:
    """Belgian structured communication: 10 digits (year + 6-digit sequence) + 2 check digits.

    The check is the 10-digit number modulo 97, or 97 when the remainder is 0.
    Example: year 2027, invoice 1 -> 2027000001, 2027000001 mod 97 = 22 -> +++202/7000/00122+++
    """
    if not 0 < value <= 999_999:
        raise ValueError("sequence value out of range for a structured reference")
    base = f"{year:04d}{value:06d}"
    check = int(base) % 97 or 97
    digits = f"{base}{check:02d}"
    return f"+++{digits[:3]}/{digits[3:7]}/{digits[7:]}+++"


def is_valid_structured_reference(reference: str) -> bool:
    digits = "".join(char for char in reference if char.isdigit())
    if len(digits) != 12:
        return False
    return (int(digits[:10]) % 97 or 97) == int(digits[10:])


# --- Drafts --------------------------------------------------------------------


def recalculate_totals(document) -> None:
    """Totals from the lines. VAT is computed per line and rounded (section 6.4)."""
    lines = list(document.lines.all())
    document.total_excl_vat = sum((line.line_total_excl_vat for line in lines), Decimal("0"))
    document.total_vat = sum(
        (
            compute_vat(line.line_total_excl_vat, document.vat_regime, document.vat_rate)
            for line in lines
        ),
        Decimal("0"),
    )
    document.total_incl_vat = document.total_excl_vat + document.total_vat


def invoiced_periods(booking: Booking) -> int:
    """Periods of a booking already on an invoice (draft, issued or paid; not cancelled)."""
    total = (
        InvoiceLine.objects.filter(invoice__booking=booking)
        .exclude(invoice__status=InvoiceStatus.CANCELLED)
        .aggregate(total=Sum("quantity"))["total"]
    )
    return total or 0


def uninvoiced_periods(booking: Booking) -> int:
    return max(booking.periods - invoiced_periods(booking), 0)


def booking_line_description(booking: Booking, start, end, periods: int, period_days: int) -> str:
    return (
        f"Stockage camping-car {booking.vehicle.plate} – du {start:%d/%m/%Y} au "
        f"{end:%d/%m/%Y} – {periods} période(s) de {period_days} jours"
    )


@transaction.atomic
def create_invoice_for_booking(booking: Booking) -> Invoice:
    """Draft invoice for the periods of the booking that are not invoiced yet.

    For a new booking that is the whole stay; after "Prolonger" it is only the added periods
    (the complementary invoice). Price and VAT come from the booking (copied at its creation).
    """
    periods = uninvoiced_periods(booking)
    if periods == 0:
        raise InvoicingError("Toutes les périodes de cette réservation sont déjà facturées.")
    period_days = AppSettings.load().period_days
    already = booking.periods - periods
    start = booking.start_date + datetime.timedelta(days=already * period_days)
    end = booking.end_date
    invoice = Invoice.objects.create(
        client=booking.vehicle.client,
        booking=booking,
        vat_regime=booking.vat_regime,
        vat_rate=booking.vat_rate,
    )
    InvoiceLine.objects.create(
        invoice=invoice,
        description=booking_line_description(booking, start, end, periods, period_days),
        service_start=start,
        service_end=end,
        quantity=periods,
        unit_price_excl_vat=booking.price_per_period,
    )
    recalculate_totals(invoice)
    invoice.save()
    return invoice


def create_manual_invoice(client) -> Invoice:
    """Empty draft for a client, with today's VAT settings. Lines are added afterwards."""
    app_settings = AppSettings.load()
    return Invoice.objects.create(
        client=client, vat_regime=app_settings.vat_regime, vat_rate=app_settings.vat_rate
    )


def delete_draft(document) -> None:
    if not document.is_draft:
        raise InvoicingError("Un document émis ne peut pas être supprimé.")
    document.delete()


# --- Snapshots and issue (8.1, 8.3) --------------------------------------------

REQUIRED_COMPANY_FIELDS = {
    "company_name": "dénomination",
    "company_address": "adresse",
    "company_vat_number": "numéro de TVA",
    "company_iban": "IBAN",
}


def missing_company_details(app_settings: AppSettings) -> list[str]:
    """Mandatory company mentions that are still empty in the settings."""
    return [
        label
        for field, label in REQUIRED_COMPANY_FIELDS.items()
        if not getattr(app_settings, field)
    ]


def missing_company_details_now() -> list[str]:
    return missing_company_details(AppSettings.load())


def _require_company_details(app_settings: AppSettings) -> None:
    missing = missing_company_details(app_settings)
    if missing:
        raise InvoicingError(
            "Complétez d'abord les informations de la société dans les Paramètres : "
            + ", ".join(missing)
            + "."
        )


def _copy_company(document, app_settings: AppSettings) -> None:
    for field in [
        "company_name",
        "company_legal_form",
        "company_address",
        "company_vat_number",
        "company_bce_number",
        "company_rpm",
        "company_iban",
        "company_bic",
        "company_email",
        "company_phone",
    ]:
        setattr(document, field, getattr(app_settings, field))


def _copy_client(document, client) -> None:
    document.client_name = client.display_name
    document.client_address = "\n".join(client.address_lines)
    document.client_vat_number = client.vat_number if client.is_business else ""
    document.client_type = client.client_type


def render_pdf(document, app_settings: AppSettings) -> bytes:
    """PDF of an issued invoice or credit note, from templates/invoicing/invoice_pdf.html."""
    from weasyprint import HTML  # imported here: loading WeasyPrint is slow

    logo_url = None
    if app_settings.company_logo:
        logo_path = Path(app_settings.company_logo.path)
        if logo_path.exists():
            logo_url = logo_path.as_uri()
    html = render_to_string(
        "invoicing/invoice_pdf.html",
        {
            "doc": document,
            "is_credit_note": isinstance(document, CreditNote),
            "lines": document.lines.all(),
            "logo_url": logo_url,
            "period_days": app_settings.period_days,
        },
    )
    return HTML(string=html).write_pdf()


def _store_pdf(document, app_settings: AppSettings) -> None:
    pdf = render_pdf(document, app_settings)
    name = f"{document.issue_date:%Y}/{document.number}.pdf"  # media/invoices/AAAA/...
    document.pdf_file.save(name, ContentFile(pdf), save=False)
    document.save(update_fields=["pdf_file", "updated_at"])


def issue_invoice(invoice: Invoice, issue_date: datetime.date | None = None) -> Invoice:
    """Assign the number, copy the client and company details, store totals and the PDF.

    Everything happens in one transaction: if the PDF cannot be generated, nothing is saved
    and the number is not used, so the numbering stays gap-free.
    """
    if not invoice.is_draft:
        raise InvoicingError("Cette facture est déjà émise.")
    if not invoice.lines.exists():
        raise InvoicingError("Ajoutez au moins une ligne avant d'émettre la facture.")
    app_settings = AppSettings.load()
    _require_company_details(app_settings)
    issue_date = issue_date or timezone.localdate()

    try:
        with transaction.atomic():
            _issue_invoice(invoice, issue_date, app_settings)
    except Exception:
        invoice.refresh_from_db()  # back to the draft as stored: no number was used
        raise
    return invoice


def _issue_invoice(invoice: Invoice, issue_date: datetime.date, app_settings) -> None:
    """The steps of `issue_invoice`, run inside its transaction."""
    value = next_number(NumberSequence.INVOICE, issue_date.year)
    invoice.number = format_number(NumberSequence.INVOICE, issue_date.year, value)
    invoice.issue_date = issue_date
    invoice.due_date = issue_date + datetime.timedelta(days=app_settings.payment_terms_days)
    invoice.structured_reference = structured_reference(issue_date.year, value)
    invoice.status = InvoiceStatus.ISSUED
    _copy_client(invoice, invoice.client)
    _copy_company(invoice, app_settings)
    recalculate_totals(invoice)
    invoice.save()
    _store_pdf(invoice, app_settings)


# --- Payments ------------------------------------------------------------------


def mark_paid(invoice: Invoice, paid_on: datetime.date, method: str, note: str = "") -> None:
    if invoice.status != InvoiceStatus.ISSUED:
        raise InvoicingError("Seule une facture émise et non payée peut être marquée payée.")
    invoice.status = InvoiceStatus.PAID
    invoice.paid_on, invoice.payment_method, invoice.payment_note = paid_on, method, note
    invoice.save()


def cancel_payment(invoice: Invoice) -> None:
    """Undo "Marquer payée" (payment is a tracking field, not accounting)."""
    if invoice.status != InvoiceStatus.PAID:
        raise InvoicingError("Cette facture n'est pas marquée payée.")
    invoice.status = InvoiceStatus.ISSUED
    invoice.paid_on, invoice.payment_method, invoice.payment_note = None, "", ""
    invoice.save()


# --- Credit notes --------------------------------------------------------------


def credited_total(invoice: Invoice) -> Decimal:
    """Total incl. VAT of the issued credit notes of an invoice."""
    total = invoice.credit_notes.filter(status=CreditNoteStatus.ISSUED).aggregate(
        total=Sum("total_incl_vat")
    )["total"]
    return total or Decimal("0")


def remaining_to_credit(invoice: Invoice) -> Decimal:
    return invoice.total_incl_vat - credited_total(invoice)


@transaction.atomic
def create_credit_note(invoice: Invoice, reason: str) -> CreditNote:
    """Draft credit note copying the invoice lines (full amount by default; the lines can be
    edited before issue to credit only part of the invoice)."""
    if invoice.is_draft:
        raise InvoicingError("Un brouillon se modifie ou se supprime : pas de note de crédit.")
    if invoice.status == InvoiceStatus.CANCELLED or remaining_to_credit(invoice) <= 0:
        raise InvoicingError("Cette facture est déjà entièrement créditée.")
    credit_note = CreditNote.objects.create(
        invoice=invoice,
        client=invoice.client,
        reason=reason,
        vat_regime=invoice.vat_regime,
        vat_rate=invoice.vat_rate,
    )
    for line in invoice.lines.all():
        CreditNoteLine.objects.create(
            credit_note=credit_note,
            description=line.description,
            service_start=line.service_start,
            service_end=line.service_end,
            quantity=line.quantity,
            unit_price_excl_vat=line.unit_price_excl_vat,
        )
    recalculate_totals(credit_note)
    credit_note.save()
    return credit_note


def issue_credit_note(
    credit_note: CreditNote, issue_date: datetime.date | None = None
) -> CreditNote:
    """Number NC-AAAA-NNNN, snapshots, PDF. Crediting the whole invoice cancels it."""
    if not credit_note.is_draft:
        raise InvoicingError("Cette note de crédit est déjà émise.")
    if not credit_note.lines.exists():
        raise InvoicingError("Ajoutez au moins une ligne avant d'émettre la note de crédit.")
    invoice = credit_note.invoice
    recalculate_totals(credit_note)
    if credit_note.total_incl_vat > remaining_to_credit(invoice):
        raise InvoicingError(
            "Le montant de la note de crédit dépasse le montant restant de la facture."
        )
    app_settings = AppSettings.load()
    _require_company_details(app_settings)
    issue_date = issue_date or timezone.localdate()

    try:
        with transaction.atomic():
            _issue_credit_note(credit_note, invoice, issue_date, app_settings)
    except Exception:
        credit_note.refresh_from_db()
        invoice.refresh_from_db()
        raise
    return credit_note


def _issue_credit_note(credit_note, invoice, issue_date, app_settings) -> None:
    """The steps of `issue_credit_note`, run inside its transaction."""
    value = next_number(NumberSequence.CREDIT_NOTE, issue_date.year)
    credit_note.number = format_number(NumberSequence.CREDIT_NOTE, issue_date.year, value)
    credit_note.issue_date = issue_date
    credit_note.status = CreditNoteStatus.ISSUED
    # The client is the one of the corrected invoice, as it was on that invoice.
    for field in ["client_name", "client_address", "client_vat_number", "client_type"]:
        setattr(credit_note, field, getattr(invoice, field))
    _copy_company(credit_note, app_settings)
    credit_note.save()
    _store_pdf(credit_note, app_settings)
    if remaining_to_credit(invoice) <= 0:
        invoice.status = InvoiceStatus.CANCELLED
        invoice.save()


# --- Email ---------------------------------------------------------------------


def email_document(document) -> str:
    """Send the stored PDF to the client. Returns the recipient address."""
    if document.is_draft or not document.pdf_file:
        raise InvoicingError("Seul un document émis peut être envoyé.")
    app_settings = AppSettings.load()
    recipient = document.client.email
    kind = "note de crédit" if isinstance(document, CreditNote) else "facture"
    body = render_to_string(
        "invoicing/email_document.txt",
        {"doc": document, "kind": kind, "is_credit_note": isinstance(document, CreditNote)},
    )
    message = EmailMessage(
        subject=f"{kind.capitalize()} {document.number} – {document.company_name}",
        body=body,
        from_email=app_settings.sender_email,
        to=[recipient],
        reply_to=[app_settings.company_email] if app_settings.company_email else None,
    )
    with document.pdf_file.open("rb") as pdf:
        message.attach(f"{document.number}.pdf", pdf.read(), "application/pdf")
    message.send()
    document.emailed_at = timezone.now()
    document.save(update_fields=["emailed_at", "updated_at"])
    return recipient


# --- Balances --------------------------------------------------------------------


def outstanding_balance(client) -> Decimal:
    """Amount still due by a client: issued, unpaid invoices minus their credit notes."""
    total = Decimal("0")
    for invoice in Invoice.objects.filter(client=client, status=InvoiceStatus.ISSUED):
        total += remaining_to_credit(invoice)
    return total
