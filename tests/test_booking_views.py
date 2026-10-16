"""M3: booking screens, HTMX helpers and the settings warnings (section 6.5)."""

import datetime
from decimal import Decimal

import pytest
from django.forms.models import model_to_dict
from django.urls import reverse

from clients.models import Client, Vehicle
from core.forms import AppSettingsForm
from core.models import AppSettings
from storage import services
from storage.models import Booking, BookingStatus
from tests.factories import (
    FLAT_PRICE,
    make_booking,
    make_client,
    make_row,
    make_vehicle,
    set_settings,
)

pytestmark = pytest.mark.django_db

MAR_1 = datetime.date(2027, 3, 1)


@pytest.fixture(autouse=True)
def demo_settings():
    set_settings(
        **FLAT_PRICE,
        default_row_length_m=Decimal("16.00"),
        vehicle_gap_m=Decimal("0.50"),
    )


def booking_data(vehicle, row, position=1, start=MAR_1, periods=2, **extra):
    data = {
        "client": vehicle.client_id,
        "vehicle": vehicle.pk,
        "start_date": start.isoformat(),
        "periods": periods,
        "row": row.pk,
        "position": position,
        "notes": "",
    }
    data.update(extra)
    return data


# --- List --------------------------------------------------------------------


def test_booking_pages_require_login(client):
    assert client.get(reverse("storage:booking_list")).status_code == 302
    assert client.get(reverse("storage:booking_create")).status_code == 302


def test_booking_list_filters(admin_client):
    row = make_row("R01")
    active = make_booking(row, 1, MAR_1, vehicle=make_vehicle(plate="1-AAA-111"))
    make_booking(
        row, 2, MAR_1, vehicle=make_vehicle(plate="1-CCC-333"), status=BookingStatus.CANCELLED
    )
    url = reverse("storage:booking_list")

    content = admin_client.get(url).content.decode()
    assert "1-AAA-111" in content and "1-CCC-333" not in content  # default: in progress only
    assert 'aria-current="page">Réservations' in content
    content = admin_client.get(url, {"statut": "toutes"}).content.decode()
    assert "1-CCC-333" in content
    content = admin_client.get(url, {"statut": "toutes", "q": "ccc"}).content.decode()
    assert "1-CCC-333" in content and "1-AAA-111" not in content
    response = admin_client.get(url, {"q": active.vehicle.client.last_name})
    assert list(response.context["page"].object_list) == [active]
    response = admin_client.get(url, {"du": "2027-06-01", "au": "2027-06-30"})
    assert list(response.context["page"].object_list) == []
    response = admin_client.get(url, {"q": "aaa"}, headers={"HX-Request": "true"})
    assert "<html" not in response.content.decode()


# --- Create / edit -----------------------------------------------------------


def test_create_booking_snapshots_price_and_computes_end_date(admin_client):
    vehicle, row = make_vehicle(), make_row("R01")
    response = admin_client.post(reverse("storage:booking_create"), booking_data(vehicle, row))
    booking = Booking.objects.get()
    assert response.url == reverse("storage:booking_detail", args=[booking.pk])
    assert booking.end_date == datetime.date(2027, 3, 28)
    assert booking.price_per_period == Decimal("45.00")
    assert booking.status == BookingStatus.RESERVED


def test_create_booking_refused_when_it_does_not_fit(admin_client):
    row = make_row("R01")
    make_booking(row, 1, MAR_1, length="8")
    vehicle = make_vehicle(length_m=Decimal("8"))
    response = admin_client.post(
        reverse("storage:booking_create"), booking_data(vehicle, row, position=2)
    )
    content = response.content.decode()
    assert "ne tient pas dans la rangée R01" in content
    assert "16,50" in content
    assert Booking.objects.count() == 1


def test_create_booking_refused_on_taken_position(admin_client):
    row = make_row("R01")
    make_booking(row, 1, MAR_1, vehicle=make_vehicle(plate="1-AAA-111"))
    response = admin_client.post(
        reverse("storage:booking_create"), booking_data(make_vehicle(), row)
    )
    assert "Position déjà occupée par 1-AAA-111" in response.content.decode()


def test_create_booking_refused_for_vehicle_already_booked(admin_client):
    row, other_row = make_row("R01"), make_row("R02")
    booking = make_booking(row, 1, MAR_1)
    data = booking_data(booking.vehicle, other_row)
    response = admin_client.post(reverse("storage:booking_create"), data)
    assert "Ce véhicule est déjà réservé" in response.content.decode()


def test_create_booking_with_blocking_requires_confirmation(admin_client):
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    make_booking(row, 1, MAR_1, periods=4, vehicle=make_vehicle(plate="XY-987-ZZ"))
    vehicle = make_vehicle(plate="AB-123-CD")
    data = booking_data(vehicle, row, position=2, periods=1)
    content = admin_client.post(reverse("storage:booking_create"), data).content.decode()
    assert "déplacer d&#x27;abord XY-987-ZZ (pos. 1)" in content
    assert "cochez « Je confirme »" in content
    assert not Booking.objects.filter(vehicle=vehicle).exists()

    data["confirm_conflicts"] = "on"
    response = admin_client.post(reverse("storage:booking_create"), data)
    assert response.status_code == 302
    assert Booking.objects.filter(vehicle=vehicle).exists()


def test_vehicle_must_belong_to_selected_client(admin_client):
    row = make_row("R01")
    vehicle = make_vehicle()
    data = booking_data(vehicle, row, client=make_client().pk)
    response = admin_client.post(reverse("storage:booking_create"), data)
    assert response.status_code == 200
    assert Booking.objects.count() == 0


def test_create_form_prefill_from_planning_and_vehicle(admin_client):
    row, vehicle = make_row("R05"), make_vehicle()
    response = admin_client.get(
        reverse("storage:booking_create"),
        {"rangee": row.pk, "debut": "2027-04-05", "vehicule": vehicle.pk},
    )
    form = response.context["form"]
    assert str(form.initial["row"]) == str(row.pk)
    assert form.initial["start_date"] == datetime.date(2027, 4, 5)
    assert form.initial["client"] == vehicle.client_id


def test_create_form_warns_when_price_missing(admin_client):
    set_settings(price_per_band=None)
    content = admin_client.get(reverse("storage:booking_create")).content.decode()
    assert "Le prix par tranche n'est pas encore défini" in content


def test_edit_booking_excludes_itself_from_fit_check(admin_client):
    row = make_row("R01")
    booking = make_booking(row, 1, MAR_1, periods=1, length="8")
    data = booking_data(booking.vehicle, row, position=1, periods=3)
    response = admin_client.post(reverse("storage:booking_edit", args=[booking.pk]), data)
    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.periods == 3
    assert booking.price_per_period == Decimal("45.00")


def test_ended_booking_cannot_be_edited(admin_client):
    booking = make_booking(make_row(), 1, MAR_1, status=BookingStatus.ENDED)
    response = admin_client.get(reverse("storage:booking_edit", args=[booking.pk]))
    assert response.status_code == 302


# --- HTMX helpers ------------------------------------------------------------


def test_vehicle_options_for_client(admin_client):
    owner = make_client()
    make_vehicle(client=owner, plate="1-OWN-001")
    make_vehicle(client=owner, plate="1-OLD-002", is_archived=True)
    make_vehicle(plate="1-OTH-003")
    content = admin_client.get(
        reverse("storage:booking_vehicles"), {"client": owner.pk}
    ).content.decode()
    assert "1-OWN-001" in content
    assert "1-OLD-002" not in content and "1-OTH-003" not in content


def test_summary_shows_end_date_and_prices(admin_client):
    set_settings(price_per_band=Decimal("12.00"), band_length_m=Decimal("2.00"))
    vehicle = make_vehicle(length_m=Decimal("7.40"))
    url = reverse("storage:booking_summary")
    params = {"start_date": "2027-03-01", "periods": "3", "vehicle": vehicle.pk}
    content = admin_client.get(url, params).content.decode()
    assert "11/04/2027" in content
    assert "4 × 2" in content and "7,40" in content  # 4 bands of 2 m
    assert "48,00" in content  # per period: 4 × 12,00 €
    assert "144,00" in content and "30,24" in content and "174,24" in content


def test_summary_without_vehicle_asks_for_it(admin_client):
    params = {"start_date": "2027-03-01", "periods": "3"}
    content = admin_client.get(reverse("storage:booking_summary"), params).content.decode()
    assert "11/04/2027" in content
    assert "choisissez le véhicule pour voir le prix" in content


def test_suggestions_endpoint_lists_best_rows(admin_client):
    make_row("R01")
    full = make_row("R02")
    make_booking(full, 1, MAR_1, length="8")
    make_booking(full, 2, MAR_1, length="7.5")
    vehicle = make_vehicle(length_m=Decimal("6"))
    response = admin_client.get(
        reverse("storage:booking_suggestions"),
        {"vehicle": vehicle.pk, "start_date": "2027-03-01", "periods": "1"},
    )
    suggestions = response.context["suggestions"]
    assert [s.row.code for s in suggestions] == ["R01"]
    assert "Choisir" in response.content.decode()


def test_suggestions_endpoint_needs_inputs(admin_client):
    response = admin_client.get(reverse("storage:booking_suggestions"))
    assert "Choisissez le véhicule" in response.content.decode()


def test_quick_vehicle_creation(admin_client):
    owner = make_client()
    url = reverse("storage:booking_quick_vehicle")
    assert "Nouveau véhicule pour" in admin_client.get(url, {"client": owner.pk}).content.decode()

    data = {"client": owner.pk, "qv-plate": "2-new 123", "qv-length_m": "6.5"}
    response = admin_client.post(url, data)
    vehicle = Vehicle.objects.get(plate="2-NEW123")
    assert vehicle.client == owner
    content = response.content.decode()
    assert f'value="{vehicle.pk}" selected' in content
    assert 'hx-swap-oob="true"' in content

    response = admin_client.post(url, {"client": owner.pk, "qv-plate": "", "qv-length_m": ""})
    assert response["HX-Retarget"] == "#quick-vehicle"


def test_booking_form_offers_new_client_and_vehicle(admin_client):
    content = admin_client.get(reverse("storage:booking_create")).content.decode()
    assert reverse("storage:booking_quick_client") in content
    assert reverse("storage:booking_quick_vehicle") in content
    assert 'id="quick-client"' in content


def test_quick_client_form_is_the_full_client_form(admin_client):
    content = admin_client.get(reverse("storage:booking_quick_client")).content.decode()
    for name in ["client_type", "company_name", "vat_number", "first_name", "last_name"]:
        assert f'name="qc-{name}"' in content
    for name in ["email", "phone", "street", "postal_code", "city", "country", "notes"]:
        assert f'name="qc-{name}"' in content


def test_quick_client_creation_selects_it_and_opens_the_vehicle_form(admin_client):
    make_client(first_name="Anne", last_name="Adam")
    data = {
        "qc-client_type": "private",
        "qc-first_name": "Marie",
        "qc-last_name": "Lambert",
        "qc-email": "marie@example.be",
        "qc-phone": "0470 11 22 33",
        "qc-street": "Rue Haute 5",
        "qc-postal_code": "6700",
        "qc-city": "Arlon",
        "qc-country": "Belgique",
    }
    response = admin_client.post(reverse("storage:booking_quick_client"), data)
    client = Client.objects.get(last_name="Lambert")
    content = response.content.decode()
    assert f'value="{client.pk}" selected' in content
    assert "Anne Adam" in content  # the other clients stay in the list
    # Out-of-band swaps: the client form closes and the new-vehicle form opens for the client.
    assert '<div id="quick-client" hx-swap-oob="true"></div>' in content
    assert '<div id="vehicle-field" hx-swap-oob="true">' in content
    assert "Nouveau véhicule pour Marie Lambert" in content
    assert 'name="qv-plate"' in content


def test_quick_client_errors_stay_in_the_client_form(admin_client):
    data = {"qc-client_type": "business", "qc-email": "info@example.be", "qc-country": "Belgique"}
    response = admin_client.post(reverse("storage:booking_quick_client"), data)
    assert response["HX-Retarget"] == "#quick-client"
    content = response.content.decode()
    assert "Le numéro de TVA est obligatoire pour une entreprise." in content
    assert content.count("Ce champ est obligatoire.") == 4  # street, postal code, city, phone
    assert Client.objects.count() == 0


def test_quick_vehicle_form_has_all_vehicle_fields(admin_client):
    url = reverse("storage:booking_quick_vehicle")
    content = admin_client.get(url, {"client": make_client().pk}).content.decode()
    for name in ["plate", "brand", "model", "length_m", "height_m", "notes"]:
        assert f'name="qv-{name}"' in content


# --- Detail and actions ------------------------------------------------------


def test_detail_shows_prices_and_move_plan(admin_client):
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    deep = make_booking(row, 2, MAR_1, periods=1, vehicle=make_vehicle(plate="AB-123-CD"))
    make_booking(row, 1, MAR_1, periods=3, vehicle=make_vehicle(plate="XY-987-ZZ"))
    content = admin_client.get(reverse("storage:booking_detail", args=[deep.pk])).content.decode()
    assert "Véhicule bloqué" in content
    assert "<strong>XY-987-ZZ</strong> (pos. 1)" in content
    assert "45,00" in content and "54,45" in content  # TTC for 1 period at 21 %


def test_status_actions(admin_client):
    booking = make_booking(make_row(), 1, MAR_1)
    url = lambda action: reverse("storage:booking_action", args=[booking.pk, action])  # noqa: E731
    admin_client.post(url("en-stock"), {"date": "2027-03-02"})
    booking.refresh_from_db()
    assert booking.status == BookingStatus.STORED
    assert booking.actual_check_in == datetime.date(2027, 3, 2)

    response = admin_client.post(url("annuler"), follow=True)
    assert "Seule une réservation pas encore entrée" in response.content.decode()

    admin_client.post(url("sortie"), {"date": "2027-03-10"})
    booking.refresh_from_db()
    assert booking.status == BookingStatus.ENDED
    assert admin_client.post(url("inconnue")).status_code == 404


def test_extend_from_detail(admin_client):
    booking = make_booking(make_row(), 1, MAR_1, periods=1)
    response = admin_client.post(
        reverse("storage:booking_extend", args=[booking.pk]), {"added_periods": "2"}, follow=True
    )
    booking.refresh_from_db()
    assert booking.periods == 3
    assert "prolongée de 2 période(s)" in response.content.decode()


def test_extend_with_blocking_asks_confirmation(admin_client):
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    make_booking(row, 2, MAR_1, periods=2, vehicle=make_vehicle(plate="1-DEP-002"))
    front = make_booking(row, 1, MAR_1, periods=1)
    url = reverse("storage:booking_extend", args=[front.pk])
    content = admin_client.post(url, {"added_periods": "2"}).content.decode()
    assert "Bloquera 1-DEP-002" in content
    front.refresh_from_db()
    assert front.periods == 1
    admin_client.post(url, {"added_periods": "2", "confirm_conflicts": "on"})
    front.refresh_from_db()
    assert front.periods == 3


def test_client_and_vehicle_pages_list_bookings(admin_client):
    booking = make_booking(make_row("R07"), 3, MAR_1)
    client_page = admin_client.get(
        reverse("clients:client_detail", args=[booking.vehicle.client_id])
    )
    vehicle_page = admin_client.get(reverse("clients:vehicle_detail", args=[booking.vehicle_id]))
    for response in (client_page, vehicle_page):
        content = response.content.decode()
        assert "R07 · pos. 3" in content
        assert reverse("storage:booking_detail", args=[booking.pk]) in content


def test_client_with_bookings_cannot_be_deleted(admin_client):
    booking = make_booking(make_row(), 1, MAR_1)
    owner = booking.vehicle.client
    url = reverse("clients:client_delete", args=[owner.pk])
    assert "ne peut pas être supprimé" in admin_client.get(url).content.decode()
    admin_client.post(url)
    assert Client.objects.filter(pk=owner.pk).exists()
    vehicle_url = reverse("clients:vehicle_delete", args=[booking.vehicle_id])
    admin_client.post(vehicle_url)
    assert Vehicle.objects.filter(pk=booking.vehicle_id).exists()


# --- Settings warnings (section 6.5) -----------------------------------------


def settings_post_data(**overrides):
    values = model_to_dict(AppSettings.load(), fields=AppSettingsForm._meta.fields)
    data = {name: "" if value is None else value for name, value in values.items()}
    data.pop("company_logo")
    data.update(overrides)
    return data


def test_bigger_gap_lists_affected_bookings_and_needs_confirmation(admin_client):
    row = make_row("R01")
    today = services.today()
    make_booking(
        row, 1, today, length="8", vehicle=make_vehicle(plate="1-BIG-008", length_m=Decimal("8"))
    )
    make_booking(row, 2, today, length="7.5")
    url = reverse("core:settings")

    response = admin_client.post(url, settings_post_data(vehicle_gap_m="0.80"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "ne tiendraient plus" in content and "1-BIG-008" in content
    assert "Enregistrer quand même" in content
    assert AppSettings.load().vehicle_gap_m == Decimal("0.50")

    response = admin_client.post(
        url, settings_post_data(vehicle_gap_m="0.80", confirm_overflow="1")
    )
    assert response.status_code == 302
    assert AppSettings.load().vehicle_gap_m == Decimal("0.80")
    assert Booking.objects.count() == 2  # nothing moved or deleted


def test_unrelated_settings_change_saves_directly(admin_client):
    row = make_row("R01")
    make_booking(row, 1, services.today(), length="8")
    response = admin_client.post(
        reverse("core:settings"), settings_post_data(company_name="Nouveau nom")
    )
    assert response.status_code == 302


def test_shrinking_row_inline_needs_confirmation(admin_client):
    row = make_row("R01", display_order=1)
    today = services.today()
    make_booking(
        row, 1, today, length="8", vehicle=make_vehicle(plate="1-BIG-008", length_m=Decimal("8"))
    )
    make_booking(row, 2, today, length="7")
    url = reverse("storage:row_edit", args=[row.pk])
    data = {"code": "R01", "display_order": "1", "length_override_m": "15", "is_active": "on"}

    content = admin_client.post(url, data).content.decode()
    assert "ne tiendraient plus dans R01" in content and "1-BIG-008" in content
    row.refresh_from_db()
    assert row.length_override_m is None

    admin_client.post(url, {**data, "confirm_overflow": "1"})
    row.refresh_from_db()
    assert row.length_override_m == Decimal("15.00")


def test_row_in_use_cannot_be_deactivated(admin_client):
    row = make_row("R01", display_order=1)
    make_booking(row, 1, services.today() + datetime.timedelta(days=10))
    url = reverse("storage:row_edit", args=[row.pk])
    data = {"code": "R01", "display_order": "1", "length_override_m": ""}
    content = admin_client.post(url, data).content.decode()
    assert "Impossible de désactiver R01" in content
    row.refresh_from_db()
    assert row.is_active
