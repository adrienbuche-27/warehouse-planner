"""M5: invoicing rules (CLAUDE.md, sections 8 and 11)."""

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.core import mail

from core.models import AppSettings, VatRegime
from invoicing import services
from invoicing.models import (
    CreditNote,
    CreditNoteStatus,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    IssuedDocumentError,
    NumberSequence,
)
from tests.factories import (
    make_booking,
    make_business,
    make_client,
    make_row,
    make_vehicle,
    set_settings,
)

pytestmark = pytest.mark.django_db

D = datetime.date
MAR_1 = D(2027, 3, 1)

COMPANY = {
    "company_name": "Stockage Ardennes",
    "company_legal_form": "SRL",
    "company_address": "Rue de la Gare 1\n6700 Arlon",
    "company_vat_number": "BE0123456749",
    "company_bce_number": "0123456749",
    "company_rpm": "RPM Liège, division Arlon",
    "company_iban": "BE68539007547034",
    "company_bic": "GKCCBEBB",
    "company_email": "contact@stockage.be",
    "company_phone": "063 12 34 56",
}


@pytest.fixture(autouse=True)
def company(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    set_settings(price_per_period=Decimal("45.00"), vat_rate=Decimal("21.00"), **COMPANY)


def booking_invoice(periods=2, client=None, plate=None):
    """Draft invoice for a new booking from 1 March 2027."""
    vehicle = make_vehicle(client=client or make_client(), **({"plate": plate} if plate else {}))
    booking = make_booking(make_row(), 1, MAR_1, periods=periods, vehicle=vehicle)
    return services.create_invoice_for_booking(booking)


# --- Structured communication (8.4) --------------------------------------------


def test_structured_reference_format_and_check_digits():
    reference = services.structured_reference(2027, 1)
    assert reference == "+++202/7000/00122+++"  # 2027000001 mod 97 = 22
    assert services.is_valid_structured_reference(reference)
    assert not services.is_valid_structured_reference("+++202/7000/00123+++")


def test_structured_reference_uses_97_when_remainder_is_zero():
    value = next(v for v in range(1, 200) if (2027_000_000 + v) % 97 == 0)
    reference = services.structured_reference(2027, value)
    assert reference.endswith("97+++")
    assert services.is_valid_structured_reference(reference)


@pytest.mark.parametrize("value", [1, 42, 999_999])
def test_structured_references_are_always_valid(value):
    assert services.is_valid_structured_reference(services.structured_reference(2026, value))


# --- Drafts --------------------------------------------------------------------


def test_invoice_from_booking_has_one_line_per_spec():
    invoice = booking_invoice(periods=2, plate="AB-123-CD")
    line = invoice.lines.get()
    assert line.description == (
        "Stockage camping-car AB-123-CD – du 01/03/2027 au 28/03/2027 – 2 période(s) de 14 jours"
    )
    assert (line.service_start, line.service_end) == (MAR_1, D(2027, 3, 28))
    assert (line.quantity, line.unit_price_excl_vat, line.line_total_excl_vat) == (
        2,
        Decimal("45.00"),
        Decimal("90.00"),
    )
    assert (invoice.total_excl_vat, invoice.total_vat, invoice.total_incl_vat) == (
        Decimal("90.00"),
        Decimal("18.90"),
        Decimal("108.90"),
    )
    assert invoice.number is None
    assert invoice.status == InvoiceStatus.DRAFT


def test_booking_cannot_be_invoiced_twice_but_extension_can():
    from storage import services as storage_services

    invoice = booking_invoice(periods=2)
    booking = invoice.booking
    with pytest.raises(services.InvoicingError, match="déjà facturées"):
        services.create_invoice_for_booking(booking)

    storage_services.extend(booking, 3)
    complementary = services.create_invoice_for_booking(booking)
    line = complementary.lines.get()
    assert line.quantity == 3
    assert (line.service_start, line.service_end) == (D(2027, 3, 29), D(2027, 5, 9))


def test_cancelled_invoice_frees_its_periods_for_a_new_invoice():
    invoice = services.issue_invoice(booking_invoice(periods=2))
    credit_note = services.create_credit_note(invoice, "Erreur")
    services.issue_credit_note(credit_note)
    assert services.uninvoiced_periods(invoice.booking) == 2


def test_drafts_have_no_number_and_can_be_deleted_without_gap():
    first = booking_invoice()
    services.delete_draft(first)
    second = services.issue_invoice(booking_invoice(), issue_date=D(2027, 1, 5))
    assert second.number == "2027-0001"
    assert not Invoice.objects.filter(pk=first.pk).exists()


# --- Numbering (8.2) -----------------------------------------------------------


def test_numbering_is_sequential_and_restarts_each_year():
    numbers = [
        services.issue_invoice(booking_invoice(), issue_date=date).number
        for date in [D(2026, 12, 30), D(2026, 12, 31), D(2027, 1, 1), D(2027, 1, 2)]
    ]
    assert numbers == ["2026-0001", "2026-0002", "2027-0001", "2027-0002"]
    assert NumberSequence.objects.get(kind="invoice", year=2026).last_value == 2


def test_credit_notes_have_their_own_sequence():
    invoice = services.issue_invoice(booking_invoice(), issue_date=D(2027, 2, 1))
    credit_note = services.issue_credit_note(
        services.create_credit_note(invoice, "Erreur"), issue_date=D(2027, 2, 2)
    )
    assert credit_note.number == "NC-2027-0001"
    assert services.issue_invoice(booking_invoice(), issue_date=D(2027, 2, 3)).number == "2027-0002"


def test_failed_pdf_does_not_use_a_number():
    invoice = booking_invoice()
    with mock.patch("invoicing.services.render_pdf", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            services.issue_invoice(invoice, issue_date=D(2027, 3, 1))
    invoice.refresh_from_db()
    assert invoice.number is None and invoice.status == InvoiceStatus.DRAFT
    assert not NumberSequence.objects.exists()
    assert services.issue_invoice(invoice, issue_date=D(2027, 3, 1)).number == "2027-0001"


def test_issue_requires_lines_and_company_details():
    empty = services.create_manual_invoice(make_client())
    with pytest.raises(services.InvoicingError, match="au moins une ligne"):
        services.issue_invoice(empty)
    set_settings(company_iban="", company_address="")
    with pytest.raises(services.InvoicingError, match="adresse, IBAN"):
        services.issue_invoice(booking_invoice())


# --- Issue: snapshots, totals, PDF (8.1, 8.3) ----------------------------------


@pytest.mark.real_pdf
def test_issue_copies_client_and_company_and_stores_pdf():
    client = make_business(
        company_name="Évasion SRL",
        vat_number="BE0553778756",
        street="Rue des Prés 76",
        postal_code="6720",
        city="Habay",
    )
    invoice = services.issue_invoice(booking_invoice(client=client), issue_date=D(2027, 3, 3))
    assert invoice.status == InvoiceStatus.ISSUED
    assert invoice.due_date == D(2027, 4, 2)  # 30 days
    assert invoice.structured_reference == services.structured_reference(2027, 1)
    assert invoice.client_name == "Évasion SRL"
    assert invoice.client_address == "Rue des Prés 76\n6720 Habay"
    assert invoice.client_vat_number == "BE0553778756"
    assert invoice.company_iban == "BE68539007547034"
    assert invoice.pdf_file.name == "invoices/2027/2027-0001.pdf"
    with invoice.pdf_file.open("rb") as pdf:
        assert pdf.read(5) == b"%PDF-"

    # Later changes to the client or the settings never alter the issued invoice.
    client.company_name = "Nouveau nom SRL"
    client.save()
    set_settings(company_name="Autre société", vat_rate=Decimal("6"))
    invoice.refresh_from_db()
    assert invoice.client_name == "Évasion SRL"
    assert invoice.company_name == "Stockage Ardennes"
    assert invoice.vat_rate == Decimal("21.00")


def pdf_html(document):
    """The HTML given to WeasyPrint (easier to check than the PDF bytes)."""
    with mock.patch("weasyprint.HTML") as html:
        services.render_pdf(document, AppSettings.load())
    return html.call_args.kwargs["string"]


def test_pdf_contains_all_mandatory_mentions():
    client = make_business(
        company_name="Évasion SRL",
        vat_number="BE0553778756",
        street="Rue des Prés 76",
        postal_code="6720",
        city="Habay",
    )
    invoice = services.issue_invoice(
        booking_invoice(client=client, plate="AB-123-CD"), issue_date=D(2027, 3, 3)
    )
    html = pdf_html(invoice)
    for mention in [
        "Facture", "2027-0001", "03/03/2027",                                  # title, number, date
        "Stockage Ardennes", "SRL", "Rue de la Gare 1", "BE0123456749",        # supplier
        "BCE : 0123456749", "RPM Liège, division Arlon",
        "Évasion SRL", "Rue des Prés 76", "TVA : BE0553778756",                # client (business)
        "Stockage camping-car AB-123-CD", "du 01/03/2027 au 28/03/2027",       # service and period
        "2 périodes", "45,00", "90,00",                                        # qty, prices
        "TVA 21 %", "18,90", "Total HTVA", "Total TVAC", "108,90",             # VAT and totals
        "02/04/2027", "BE68 5390 0754 7034", "GKCCBEBB",                       # due date, IBAN/BIC
        invoice.structured_reference,                                          # structured comm.
    ]:  # fmt: skip
        assert mention in html, mention
    assert "franchise" not in html


def test_private_client_has_no_vat_number_on_pdf():
    client = make_client(first_name="Marie", last_name="Lambert", vat_number="")
    invoice = services.issue_invoice(booking_invoice(client=client))
    html = pdf_html(invoice)
    assert "Marie Lambert" in html
    assert html.count("TVA : ") == 1  # only the supplier's


def test_franchise_regime_gives_zero_vat_and_the_mention():
    set_settings(vat_regime=VatRegime.FRANCHISE)
    invoice = services.issue_invoice(booking_invoice(periods=2))
    assert invoice.total_vat == Decimal("0.00")
    assert invoice.total_incl_vat == invoice.total_excl_vat == Decimal("90.00")
    assert "Régime particulier de franchise des petites entreprises" in pdf_html(invoice)


def test_vat_is_rounded_per_line():
    invoice = services.create_manual_invoice(make_client())
    for price in ["12.50", "12.50"]:
        InvoiceLine.objects.create(
            invoice=invoice, description="x", quantity=1, unit_price_excl_vat=Decimal(price)
        )
    services.recalculate_totals(invoice)
    # 2.625 rounded per line = 2.63 + 2.63 (not 5.25 on the total)
    assert invoice.total_vat == Decimal("5.26")


# --- Immutability (8.2, 8.3) -----------------------------------------------------


def test_issued_invoice_is_read_only():
    invoice = services.issue_invoice(booking_invoice())
    invoice.client_name = "Autre"
    with pytest.raises(IssuedDocumentError):
        invoice.save()
    invoice.refresh_from_db()
    invoice.total_incl_vat = Decimal("1")
    with pytest.raises(IssuedDocumentError):
        invoice.save()
    line = invoice.lines.get()
    line.unit_price_excl_vat = Decimal("1")
    with pytest.raises(IssuedDocumentError):
        line.save()
    with pytest.raises(IssuedDocumentError):
        line.delete()
    with pytest.raises(IssuedDocumentError):
        InvoiceLine.objects.create(
            invoice=invoice, description="ajout", quantity=1, unit_price_excl_vat=1
        )


def test_issued_invoice_cannot_be_deleted():
    invoice = services.issue_invoice(booking_invoice())
    with pytest.raises(IssuedDocumentError):
        invoice.delete()
    with pytest.raises(IssuedDocumentError):
        Invoice.objects.all().delete()
    with pytest.raises(services.InvoicingError):
        services.delete_draft(invoice)
    assert Invoice.objects.filter(pk=invoice.pk).exists()


def test_payment_tracking_is_allowed_after_issue():
    invoice = services.issue_invoice(booking_invoice())
    services.mark_paid(invoice, D(2027, 3, 10), "transfer", "extrait 12")
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_on, invoice.payment_method) == (
        "paid",
        D(2027, 3, 10),
        "transfer",
    )
    with pytest.raises(services.InvoicingError):
        services.mark_paid(invoice, D(2027, 3, 11), "cash")
    services.cancel_payment(invoice)
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_on, invoice.payment_note) == ("issued", None, "")


def test_overdue():
    invoice = services.issue_invoice(
        booking_invoice(), issue_date=services.today() - datetime.timedelta(days=40)
    )
    assert invoice.is_overdue
    services.mark_paid(invoice, services.today(), "cash")
    assert not invoice.is_overdue


# --- Credit notes ----------------------------------------------------------------


def test_full_credit_note_cancels_the_invoice():
    invoice = services.issue_invoice(booking_invoice(periods=2), issue_date=D(2027, 3, 3))
    credit_note = services.create_credit_note(invoice, "Erreur de période")
    assert credit_note.total_incl_vat == invoice.total_incl_vat
    services.issue_credit_note(credit_note, issue_date=D(2027, 3, 4))
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.CANCELLED
    assert credit_note.status == CreditNoteStatus.ISSUED
    assert credit_note.client_name == invoice.client_name
    html = pdf_html(credit_note)
    for mention in [
        "Note de crédit",
        "NC-2027-0001",
        "2027-0001",
        "03/03/2027",
        "Erreur de période",
    ]:
        assert mention in html
    with pytest.raises(services.InvoicingError, match="entièrement créditée"):
        services.create_credit_note(invoice, "encore")


def test_partial_credit_note_keeps_the_invoice_open():
    invoice = services.issue_invoice(booking_invoice(periods=2))
    credit_note = services.create_credit_note(invoice, "Une période en moins")
    line = credit_note.lines.get()
    line.quantity = 1
    line.save()
    services.issue_credit_note(credit_note)
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.ISSUED
    assert services.remaining_to_credit(invoice) == Decimal("54.45")
    assert services.outstanding_balance(invoice.client) == Decimal("54.45")

    second = services.create_credit_note(invoice, "Le reste")
    with pytest.raises(services.InvoicingError, match="dépasse"):
        services.issue_credit_note(second)  # copies both periods again: too much
    line = second.lines.get()
    line.quantity = 1
    line.save()
    services.issue_credit_note(second)
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.CANCELLED


def test_issued_credit_note_is_read_only_and_undeletable():
    invoice = services.issue_invoice(booking_invoice())
    credit_note = services.issue_credit_note(services.create_credit_note(invoice, "Erreur"))
    credit_note.reason = "Autre"
    with pytest.raises(IssuedDocumentError):
        credit_note.save()
    with pytest.raises(IssuedDocumentError):
        CreditNote.objects.all().delete()


def test_no_credit_note_on_a_draft():
    with pytest.raises(services.InvoicingError):
        services.create_credit_note(booking_invoice(), "Erreur")


# --- Email ---------------------------------------------------------------------


def test_email_sends_the_stored_pdf_to_the_client():
    client = make_client(email="marie@example.be")
    invoice = services.issue_invoice(booking_invoice(client=client))
    assert services.email_document(invoice) == "marie@example.be"
    message = mail.outbox[0]
    assert message.to == ["marie@example.be"]
    assert message.from_email == "contact@stockage.be"
    assert invoice.number in message.subject
    assert invoice.structured_reference in message.body
    assert "BE68 5390 0754 7034" in message.body
    ((name, content, mimetype),) = message.attachments
    assert (name, mimetype) == (f"{invoice.number}.pdf", "application/pdf")
    assert content.startswith(b"%PDF-")
    invoice.refresh_from_db()
    assert invoice.emailed_at is not None


def test_draft_cannot_be_emailed():
    with pytest.raises(services.InvoicingError):
        services.email_document(booking_invoice())
