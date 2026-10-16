"""M5: invoicing screens."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from invoicing import services
from invoicing.models import CreditNote, Invoice, InvoiceStatus
from tests.factories import make_booking, make_client, make_row, make_vehicle, set_settings
from tests.test_invoicing import COMPANY

pytestmark = pytest.mark.django_db

MAR_1 = datetime.date(2027, 3, 1)


@pytest.fixture(autouse=True)
def company(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    set_settings(price_per_period=Decimal("45.00"), **COMPANY)


def make_invoice(issued=False, periods=2, client=None, issue_date=None):
    vehicle = make_vehicle(client=client or make_client())
    booking = make_booking(make_row(), 1, MAR_1, periods=periods, vehicle=vehicle)
    invoice = services.create_invoice_for_booking(booking)
    if issued:
        services.issue_invoice(invoice, issue_date=issue_date)
    return invoice


def test_invoice_pages_require_login(client):
    assert client.get(reverse("invoicing:invoice_list")).status_code == 302
    invoice = make_invoice(issued=True)
    assert (
        client.get(reverse("invoicing:document_pdf", args=["facture", invoice.pk])).status_code
        == 302
    )


def test_invoice_from_booking_button(admin_client):
    booking = make_booking(make_row(), 1, MAR_1, periods=2)
    content = admin_client.get(
        reverse("storage:booking_detail", args=[booking.pk])
    ).content.decode()
    assert "Créer la facture" in content
    response = admin_client.post(reverse("invoicing:invoice_from_booking", args=[booking.pk]))
    invoice = Invoice.objects.get()
    assert response.url == reverse("invoicing:invoice_detail", args=[invoice.pk])
    content = admin_client.get(
        reverse("storage:booking_detail", args=[booking.pk])
    ).content.decode()
    assert "Toutes les périodes sont facturées" in content
    response = admin_client.post(
        reverse("invoicing:invoice_from_booking", args=[booking.pk]), follow=True
    )
    assert "déjà facturées" in response.content.decode()


def test_complementary_invoice_after_extension(admin_client):
    invoice = make_invoice(issued=True, periods=2)
    booking = invoice.booking
    admin_client.post(reverse("storage:booking_extend", args=[booking.pk]), {"added_periods": "1"})
    content = admin_client.get(
        reverse("storage:booking_detail", args=[booking.pk])
    ).content.decode()
    assert "Facturer 1 période non facturée" in content


def test_edit_draft_lines_and_totals(admin_client):
    invoice = make_invoice()
    line = invoice.lines.get()
    url = reverse("invoicing:invoice_edit", args=[invoice.pk])
    assert admin_client.get(url).status_code == 200
    data = {
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "1",
        "lines-0-id": line.pk,
        "lines-0-invoice": invoice.pk,
        "lines-0-description": line.description,
        "lines-0-service_start": "2027-03-01",
        "lines-0-service_end": "2027-03-28",
        "lines-0-quantity": "2",
        "lines-0-unit_price_excl_vat": "45.00",
        "lines-1-invoice": invoice.pk,
        "lines-1-description": "Frais de dossier",
        "lines-1-quantity": "1",
        "lines-1-unit_price_excl_vat": "10.00",
    }
    response = admin_client.post(url, data)
    assert response.status_code == 302
    invoice.refresh_from_db()
    assert invoice.lines.count() == 2
    assert invoice.total_excl_vat == Decimal("100.00")
    assert invoice.total_incl_vat == Decimal("121.00")


def test_issue_from_detail_page(admin_client):
    invoice = make_invoice()
    response = admin_client.post(reverse("invoicing:invoice_issue", args=[invoice.pk]), follow=True)
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.ISSUED
    content = response.content.decode()
    assert f"Facture {invoice.number} émise" in content
    assert "Télécharger le PDF" in content and "Marquer payée" in content
    # Read-only from now on.
    response = admin_client.get(reverse("invoicing:invoice_edit", args=[invoice.pk]))
    assert response.status_code == 302
    response = admin_client.post(
        reverse("invoicing:invoice_delete", args=[invoice.pk]), follow=True
    )
    assert "ne peut pas être supprimé" in response.content.decode()
    assert Invoice.objects.filter(pk=invoice.pk).exists()


def test_issue_refused_without_company_details(admin_client):
    set_settings(company_vat_number="")
    invoice = make_invoice()
    content = admin_client.get(
        reverse("invoicing:invoice_detail", args=[invoice.pk])
    ).content.decode()
    assert "complétez les informations de la société" in content
    response = admin_client.post(reverse("invoicing:invoice_issue", args=[invoice.pk]), follow=True)
    assert "numéro de TVA" in response.content.decode()
    invoice.refresh_from_db()
    assert invoice.is_draft


def test_issue_refused_while_the_client_address_is_incomplete(admin_client):
    client = make_client(postal_code="")
    invoice = make_invoice(client=client)
    detail_url = reverse("invoicing:invoice_detail", args=[invoice.pk])
    edit_url = reverse("clients:client_edit", args=[client.pk])
    content = admin_client.get(detail_url).content.decode()
    assert "complétez la fiche du client" in content and "code postal" in content
    assert f"{edit_url}?next={detail_url}" in content

    response = admin_client.post(reverse("invoicing:invoice_issue", args=[invoice.pk]), follow=True)
    assert "Complétez d&#x27;abord la fiche du client" in response.content.decode()
    invoice.refresh_from_db()
    assert invoice.is_draft

    # "Modifier le client" comes back to the invoice once the client is saved.
    content = admin_client.get(edit_url, {"next": detail_url}).content.decode()
    assert f'name="next" value="{detail_url}"' in content
    data = {
        "client_type": "private",
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
        "street": client.street,
        "postal_code": "6700",
        "city": client.city,
        "country": "Belgique",
        "next": detail_url,
    }
    assert admin_client.post(edit_url, data).url == detail_url
    assert "complétez la fiche du client" not in admin_client.get(detail_url).content.decode()


def test_client_edit_ignores_an_external_next_url(admin_client):
    client = make_client()
    data = {
        "client_type": "private",
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
        "street": client.street,
        "postal_code": client.postal_code,
        "city": client.city,
        "country": "Belgique",
        "next": "https://example.com/",
    }
    response = admin_client.post(reverse("clients:client_edit", args=[client.pk]), data)
    assert response.url == reverse("clients:client_detail", args=[client.pk])


def test_delete_draft(admin_client):
    invoice = make_invoice()
    booking = invoice.booking
    response = admin_client.post(reverse("invoicing:invoice_delete", args=[invoice.pk]))
    assert response.url == reverse("storage:booking_detail", args=[booking.pk])
    assert not Invoice.objects.exists()


def test_manual_invoice(admin_client):
    client = make_client()
    response = admin_client.post(reverse("invoicing:invoice_create"), {"client": client.pk})
    invoice = Invoice.objects.get()
    assert invoice.booking is None
    assert response.url == reverse("invoicing:invoice_edit", args=[invoice.pk])


def test_pay_and_unpay(admin_client):
    invoice = make_invoice(issued=True)
    admin_client.post(
        reverse("invoicing:invoice_pay", args=[invoice.pk]),
        {"paid_on": "2027-03-10", "payment_method": "cash", "payment_note": "au comptoir"},
    )
    invoice.refresh_from_db()
    assert (invoice.status, invoice.payment_method) == (InvoiceStatus.PAID, "cash")
    content = admin_client.get(
        reverse("invoicing:invoice_detail", args=[invoice.pk])
    ).content.decode()
    assert "Payée le <strong>10/03/2027</strong> (Espèces)" in content
    admin_client.post(reverse("invoicing:invoice_unpay", args=[invoice.pk]))
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.ISSUED


def test_pdf_download(admin_client):
    invoice = make_invoice(issued=True)
    response = admin_client.get(reverse("invoicing:document_pdf", args=["facture", invoice.pk]))
    assert response["Content-Type"] == "application/pdf"
    assert f'filename="{invoice.number}.pdf"' in response["Content-Disposition"]
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    draft = make_invoice()
    assert (
        admin_client.get(reverse("invoicing:document_pdf", args=["facture", draft.pk])).status_code
        == 404
    )
    assert (
        admin_client.get(reverse("invoicing:document_pdf", args=["autre", invoice.pk])).status_code
        == 404
    )


def test_email_from_detail(admin_client, mailoutbox):
    invoice = make_invoice(issued=True, client=make_client(email="paul@example.be"))
    response = admin_client.post(
        reverse("invoicing:document_email", args=["facture", invoice.pk]), follow=True
    )
    assert f"{invoice.number} envoyé à paul@example.be" in response.content.decode()
    assert len(mailoutbox) == 1


def test_credit_note_flow(admin_client):
    invoice = make_invoice(issued=True, periods=2)
    response = admin_client.post(
        reverse("invoicing:credit_note_create", args=[invoice.pk]), {"reason": "Annulation"}
    )
    credit_note = CreditNote.objects.get()
    assert response.url == reverse("invoicing:credit_note_detail", args=[credit_note.pk])
    content = admin_client.get(response.url).content.decode()
    assert "Reste à créditer" in content
    response = admin_client.post(
        reverse("invoicing:credit_note_issue", args=[credit_note.pk]), follow=True
    )
    credit_note.refresh_from_db()
    assert credit_note.number.startswith("NC-")
    assert f"La facture {invoice.number} est annulée" in response.content.decode()
    content = admin_client.get(reverse("invoicing:credit_note_list")).content.decode()
    assert credit_note.number in content


def test_partial_credit_note_by_editing_lines(admin_client):
    invoice = make_invoice(issued=True, periods=2)
    admin_client.post(
        reverse("invoicing:credit_note_create", args=[invoice.pk]), {"reason": "Une période"}
    )
    credit_note = CreditNote.objects.get()
    line = credit_note.lines.get()
    data = {
        "reason": "Une période",
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "1",
        "lines-0-id": line.pk,
        "lines-0-credit_note": credit_note.pk,
        "lines-0-description": line.description,
        "lines-0-quantity": "1",
        "lines-0-unit_price_excl_vat": "45.00",
    }
    response = admin_client.post(reverse("invoicing:credit_note_edit", args=[credit_note.pk]), data)
    assert response.status_code == 302
    admin_client.post(reverse("invoicing:credit_note_issue", args=[credit_note.pk]))
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.ISSUED
    assert services.remaining_to_credit(invoice) == Decimal("54.45")


def test_invoice_list_filters_and_totals(admin_client):
    today = services.today()
    overdue = make_invoice(issued=True, issue_date=today - datetime.timedelta(days=45))
    recent = make_invoice(issued=True, issue_date=today)
    draft = make_invoice()
    url = reverse("invoicing:invoice_list")

    response = admin_client.get(url)
    assert response.context["totals"]["incl"] == Decimal("326.70")  # 3 × 108,90
    assert 'aria-current="page">Factures' in response.content.decode()

    response = admin_client.get(url, {"retard": "1"})
    assert list(response.context["page"].object_list) == [overdue]
    assert "en retard" in response.content.decode()

    response = admin_client.get(url, {"statut": "draft"})
    assert list(response.context["page"].object_list) == [draft]

    response = admin_client.get(url, {"q": recent.number})
    assert list(response.context["page"].object_list) == [recent]


def test_client_page_shows_invoices_and_balance(admin_client):
    client = make_client()
    make_invoice(issued=True, client=client)
    paid = make_invoice(issued=True, client=client)
    services.mark_paid(paid, services.today(), "transfer")
    content = admin_client.get(reverse("clients:client_detail", args=[client.pk])).content.decode()
    assert "Solde à payer : <strong>108,90" in content
    assert paid.number in content


def test_booking_with_invoice_protects_client_from_deletion(admin_client):
    invoice = make_invoice(issued=True)
    url = reverse("clients:client_delete", args=[invoice.client_id])
    assert "ne peut pas être supprimé" in admin_client.get(url).content.decode()
