"""Price per length band (backlog #3): bands, snapshot, recalculation after a length change."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from core.pricing import band_count
from invoicing import services as invoicing_services
from invoicing.models import InvoiceStatus
from storage import services
from storage.models import Booking
from tests.factories import (
    BANDS_2M_12EUR,
    make_booking,
    make_row,
    make_vehicle,
    set_settings,
)
from tests.test_invoicing import COMPANY

pytestmark = pytest.mark.django_db

MAR_1 = datetime.date(2027, 3, 1)


@pytest.fixture(autouse=True)
def band_settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    set_settings(**BANDS_2M_12EUR, vat_rate=Decimal("21.00"), **COMPANY)


def booking_for(length, periods=3):
    vehicle = make_vehicle(length_m=Decimal(length))
    return make_booking(make_row(), 1, MAR_1, periods=periods, vehicle=vehicle)


def set_length(vehicle, length):
    vehicle.length_m = Decimal(length)
    vehicle.save()


@pytest.mark.parametrize(
    ("length", "bands"),
    [("7.40", 4), ("6.00", 3), ("6.01", 4), ("0.50", 1), ("2.00", 1), ("8.00", 4)],
)
def test_a_started_band_counts_in_full(length, bands):
    assert band_count(Decimal(length), Decimal("2.00")) == bands


def test_booking_records_bands_and_price_per_period():
    booking = booking_for("7.40")
    booking.refresh_from_db()
    assert booking.band_length_m == Decimal("2.00")
    assert booking.price_per_band == Decimal("12.00")
    assert booking.billed_length_m == Decimal("7.40")
    assert booking.band_count == 4
    assert booking.price_per_period == Decimal("48.00")
    assert booking.totals.excl_vat == Decimal("144.00")  # no minimum charge


def test_band_size_from_the_settings():
    set_settings(band_length_m=Decimal("2.50"))
    assert booking_for("7.40").band_count == 3


# --- Length corrected after booking ----------------------------------------------


def test_length_change_recalculates_bookings_not_invoiced():
    booking = booking_for("7.40")
    set_length(booking.vehicle, "8.20")
    [change] = services.refresh_vehicle_prices(booking.vehicle)
    assert change.applied and (change.old_bands, change.new_bands) == (4, 5)
    assert "5 tranche(s) au lieu de 4" in change.as_text()
    booking.refresh_from_db()
    assert (booking.billed_length_m, booking.band_count) == (Decimal("8.20"), 5)
    assert booking.price_per_period == Decimal("60.00")


def test_length_change_within_the_same_band_keeps_the_price_silently():
    booking = booking_for("7.40")
    set_length(booking.vehicle, "7.90")
    assert services.refresh_vehicle_prices(booking.vehicle) == []
    booking.refresh_from_db()
    assert booking.billed_length_m == Decimal("7.90")  # the invoice line shows the right length
    assert booking.price_per_period == Decimal("48.00")


@pytest.mark.parametrize("issued", [False, True])
def test_invoiced_booking_keeps_its_price(issued):
    booking = booking_for("7.40")
    invoice = invoicing_services.create_invoice_for_booking(booking)
    if issued:
        invoicing_services.issue_invoice(invoice)
    set_length(booking.vehicle, "8.20")
    [change] = services.refresh_vehicle_prices(booking.vehicle)
    assert not change.applied
    assert "déjà facturée" in change.as_text() and "note de crédit" in change.as_text()
    booking.refresh_from_db()
    assert (booking.billed_length_m, booking.band_count) == (Decimal("7.40"), 4)
    assert booking.price_per_period == Decimal("48.00")


def test_draft_recreated_after_a_length_change_has_the_new_price():
    booking = booking_for("7.40")
    invoicing_services.create_invoice_for_booking(booking).delete()
    set_length(booking.vehicle, "8.20")  # changed without passing through the vehicle form
    line = invoicing_services.create_invoice_for_booking(booking).lines.get()
    assert line.unit_price_excl_vat == Decimal("60.00")
    assert "8,20 m, soit 5\u00a0tranches" in line.description


def test_credit_note_then_new_invoice_uses_the_corrected_length():
    booking = booking_for("7.40")
    invoice = invoicing_services.create_invoice_for_booking(booking)
    invoicing_services.issue_invoice(invoice)
    set_length(booking.vehicle, "8.20")
    credit_note = invoicing_services.create_credit_note(invoice, "Longueur erronée")
    invoicing_services.issue_credit_note(credit_note)
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.CANCELLED

    new_line = invoicing_services.create_invoice_for_booking(booking).lines.get()
    assert new_line.unit_price_excl_vat == Decimal("60.00")


def test_extension_invoice_keeps_the_invoiced_price():
    booking = booking_for("7.40", periods=2)
    invoicing_services.create_invoice_for_booking(booking)
    services.extend(booking, 1)
    set_length(booking.vehicle, "8.20")
    line = invoicing_services.create_invoice_for_booking(booking).lines.get()
    assert line.quantity == 1
    assert line.unit_price_excl_vat == Decimal("48.00")  # same price as the first invoice
    assert "7,40 m, soit 4\u00a0tranches" in line.description


def test_flat_price_bookings_are_left_alone():
    booking = booking_for("7.40")
    Booking.objects.filter(pk=booking.pk).update(band_length_m=None, price_per_band=None)
    booking.refresh_from_db()
    set_length(booking.vehicle, "8.20")
    assert services.refresh_vehicle_prices(booking.vehicle) == []
    booking.refresh_from_db()
    assert booking.price_per_period == Decimal("48.00")


# --- Screens -----------------------------------------------------------------------


def vehicle_data(vehicle, **changes):
    data = {
        "client": vehicle.client_id,
        "plate": vehicle.plate,
        "brand": vehicle.brand,
        "model": vehicle.model,
        "length_m": vehicle.length_m,
        "height_m": "",
        "notes": "",
    }
    data.update(changes)
    return data


def test_vehicle_form_reports_recalculated_and_kept_prices(admin_client):
    vehicle = make_vehicle(length_m=Decimal("7.40"))
    make_booking(make_row(), 1, MAR_1, periods=1, vehicle=vehicle)
    invoiced = make_booking(make_row(), 1, datetime.date(2027, 6, 7), periods=1, vehicle=vehicle)
    invoicing_services.create_invoice_for_booking(invoiced)
    url = reverse("clients:vehicle_edit", args=[vehicle.pk])
    response = admin_client.post(url, vehicle_data(vehicle, length_m="8.20"), follow=True)
    content = response.content.decode()
    assert "Prix recalculé pour la réservation du 01/03/2027 au 14/03/2027" in content
    assert "60,00" in content
    assert "La réservation du 07/06/2027 au 20/06/2027 est déjà facturée" in content


def test_editing_a_booking_with_another_vehicle_recalculates_its_price(admin_client):
    booking = booking_for("7.40", periods=1)
    longer = make_vehicle(client=booking.vehicle.client, length_m=Decimal("8.20"))
    data = {
        "client": longer.client_id,
        "vehicle": longer.pk,
        "start_date": MAR_1.isoformat(),
        "periods": 1,
        "row": booking.row_id,
        "position": 1,
        "notes": "",
    }
    response = admin_client.post(reverse("storage:booking_edit", args=[booking.pk]), data)
    assert response.status_code == 302
    booking.refresh_from_db()
    assert (booking.band_count, booking.price_per_period) == (5, Decimal("60.00"))


def test_summary_of_an_invoiced_booking_shows_the_invoiced_price(admin_client):
    booking = booking_for("7.40", periods=1)
    invoicing_services.create_invoice_for_booking(booking)
    longer = make_vehicle(client=booking.vehicle.client, length_m=Decimal("8.20"))
    params = {"start_date": "2027-03-01", "periods": "1", "vehicle": longer.pk}
    params["booking"] = booking.pk
    content = admin_client.get(reverse("storage:booking_summary"), params).content.decode()
    assert "48,00" in content and "60,00" not in content


def test_booking_detail_shows_the_bands(admin_client):
    booking = booking_for("7.40")
    content = admin_client.get(
        reverse("storage:booking_detail", args=[booking.pk])
    ).content.decode()
    assert "4 tranches de 2" in content and "12,00" in content and "48,00" in content


def test_vehicle_dropdown_changes_tell_the_form_to_recompute_the_price(admin_client):
    vehicle = make_vehicle()
    response = admin_client.get(reverse("storage:booking_vehicles"), {"client": vehicle.client_id})
    assert response["HX-Trigger-After-Settle"] == "vehicle-selected"
    content = admin_client.get(reverse("storage:booking_create")).content.decode()
    assert "vehicle-selected from:body" in content and "#id_vehicle" in content
