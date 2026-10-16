"""Warehouse map (backlog #4): rows as strips, vehicles by position, row status for a booking."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from storage import services
from storage.models import BookingStatus
from storage.warehouse_map import RowStatus, build_map
from tests.factories import FLAT_PRICE, make_booking, make_row, make_vehicle, set_settings

pytestmark = pytest.mark.django_db

D = datetime.date
MAR_1 = D(2027, 3, 1)
MAR_14 = D(2027, 3, 14)


@pytest.fixture(autouse=True)
def demo_settings():
    set_settings(**FLAT_PRICE, default_row_length_m=Decimal("16.00"), vehicle_gap_m=Decimal("0.50"))


def map_row(warehouse_map, row):
    return next(r for r in warehouse_map.rows if r.row == row)


# --- Building the map ------------------------------------------------------------


def test_one_day_map_draws_vehicles_by_position():
    row = make_row("R01")
    deep = make_booking(row, 2, MAR_1, length="6.00")
    aisle = make_booking(row, 1, MAR_1, length="8.00")
    make_booking(row, 3, D(2027, 6, 7), length="5.00")  # not there on 1 March
    r = map_row(build_map(MAR_1), row)
    assert [p.position for p in r.positions] == [1, 2]
    assert [p.vehicles[0].booking for p in r.positions] == [aisle, deep]
    assert [p.width for p in r.positions] == ["50.00", "37.50"]  # share of 16 m
    assert r.peak_m == Decimal("14.50") and r.free_m == Decimal("1.50")
    assert not any(v.partial for p in r.positions for v in p.vehicles)


def test_shorter_rows_are_drawn_shorter_and_inactive_rows_hidden():
    long_row = make_row("R01", length_override_m=Decimal("20.00"))
    short_row = make_row("R02")
    make_row("R03", is_active=False)
    warehouse_map = build_map(MAR_1)
    assert [r.row.code for r in warehouse_map.rows] == ["R01", "R02"]
    assert map_row(warehouse_map, long_row).width == "100.00"
    assert map_row(warehouse_map, short_row).width == "80.00"


def test_period_map_stacks_vehicles_using_a_position_one_after_another():
    row = make_row("R01")
    first = make_booking(row, 1, MAR_1, periods=1, length="6.00")
    second = make_booking(row, 1, D(2027, 3, 15), periods=1, length="8.00")
    whole = make_booking(row, 2, MAR_1, periods=2, length="5.00")
    ended = make_booking(row, 3, MAR_1, periods=2, length="5.00", status=BookingStatus.ENDED)
    r = map_row(build_map(MAR_1, D(2027, 3, 28)), row)
    [pos1, pos2] = r.positions
    assert [v.booking for v in pos1.vehicles] == [first, second]
    assert pos1.width == "50.00"  # the longest of the two (8 m)
    assert [v.width for v in pos1.vehicles] == ["75.00", "100.00"]
    assert [v.partial for v in pos1.vehicles] == [True, True]
    assert [v.booking for v in pos2.vehicles] == [whole] and not pos2.vehicles[0].partial
    assert ended not in [v.booking for p in r.positions for v in p.vehicles]
    assert r.peak_m == Decimal("13.50")  # 8 + 0,5 + 5, never the three at the same time


def test_map_totals():
    make_booking(make_row("R01"), 1, MAR_1, length="8.00")
    make_row("R02")
    warehouse_map = build_map(MAR_1)
    assert warehouse_map.vehicle_count == 1
    assert warehouse_map.total_free_m == Decimal("24.00")
    assert warehouse_map.occupancy_percent == 25


# --- Row status for the vehicle being booked ----------------------------------------


def test_row_status_for_a_new_booking():
    roomy, tight, full, blocked = (make_row(code) for code in ["R01", "R02", "R03", "R04"])
    make_booking(tight, 1, MAR_1, periods=1, length="8.00")
    make_booking(full, 1, MAR_1, periods=1, length="8.00")
    make_booking(full, 2, MAR_1, periods=1, length="7.00")
    # Stays longer, near the aisle: the new vehicle (deeper) would be boxed in when leaving.
    make_booking(blocked, 1, MAR_1, periods=3, length="5.00")
    for position in (2, 3):  # positions 2 and 3 already taken until the same date
        make_booking(blocked, position, MAR_1, periods=3, length="1.00")
    vehicle = make_vehicle(length_m=Decimal("7.00"))
    warehouse_map = build_map(MAR_1, MAR_14, vehicle)

    assert map_row(warehouse_map, full).status == RowStatus.FULL
    assert map_row(warehouse_map, full).position is None
    for row in (roomy, tight):
        r = map_row(warehouse_map, row)
        assert r.status == RowStatus.FITS and r.can_pick and r.starred
    assert map_row(warehouse_map, tight).position == 2
    conflict = map_row(warehouse_map, blocked)
    assert conflict.status == RowStatus.CONFLICT and conflict.position == 4
    assert any("déplacer d'abord" in warning for warning in conflict.warnings)


def test_only_the_rows_of_the_five_best_suggestions_are_starred():
    rows = [make_row(f"R{n:02d}") for n in range(1, 8)]
    vehicle = make_vehicle(length_m=Decimal("7.00"))
    warehouse_map = build_map(MAR_1, MAR_14, vehicle)
    assert [map_row(warehouse_map, row).starred for row in rows] == [True] * 5 + [False] * 2


def test_editing_a_booking_leaves_it_out_of_the_map():
    row = make_row("R01")
    booking = make_booking(row, 1, MAR_1, periods=1, length="8.00")
    warehouse_map = build_map(MAR_1, MAR_14, booking.vehicle, exclude_booking=booking)
    r = map_row(warehouse_map, row)
    assert r.positions == [] and r.status == RowStatus.FITS and r.position == 1


# --- Screens -----------------------------------------------------------------------


def test_booking_form_loads_the_map(admin_client):
    content = admin_client.get(reverse("storage:booking_create")).content.decode()
    assert reverse("storage:booking_map") in content
    assert "pickMapRow" in content


def test_booking_map_needs_vehicle_and_dates(admin_client):
    content = admin_client.get(reverse("storage:booking_map")).content.decode()
    assert "Choisissez le véhicule, la date d'entrée et le nombre de périodes" in content


def test_booking_map_marks_rows_and_the_selected_one(admin_client):
    row = make_row("R01")
    neighbour = make_vehicle(plate="XY-987", length_m=Decimal("8.00"))
    make_booking(row, 1, MAR_1, periods=1, vehicle=neighbour)
    vehicle = make_vehicle(length_m=Decimal("7.00"))
    params = {"vehicle": vehicle.pk, "start_date": "2027-03-01", "periods": "1", "row": row.pk}
    content = admin_client.get(reverse("storage:booking_map"), params).content.decode()
    assert f'data-row="{row.pk}" data-position="2"' in content
    assert 'class="map-row selected"' in content
    assert "XY-987" in content and "✓" in content and "★" in content
    assert 'style="flex-basis: 50.00%"' in content  # never "50,00" with the French locale


def test_booking_map_when_the_vehicle_is_already_booked(admin_client):
    row = make_row("R01")
    booking = make_booking(row, 1, MAR_1, periods=1)
    params = {"vehicle": booking.vehicle_id, "start_date": "2027-03-01", "periods": "1"}
    content = admin_client.get(reverse("storage:booking_map"), params).content.decode()
    assert "déjà réservé sur cette période" in content
    assert "data-row=" not in content  # nothing to pick


# --- "Plan de l'entrepôt": space management ------------------------------------------


def test_warehouse_map_page(admin_client):
    row = make_row("R01")
    booking = make_booking(row, 1, MAR_1, periods=1, length="8.00")
    url = reverse("storage:planning_map")
    content = admin_client.get(url, {"date": "2027-03-05"}).content.decode()
    assert "<h1>Plan de l'entrepôt</h1>" in content
    assert "1 véhicule, 50 % occupé" in content
    assert reverse("storage:booking_detail", args=[booking.pk]) in content
    new_here = f"{reverse('storage:booking_create')}?rangee={row.pk}&amp;debut=2027-03-05"
    assert new_here in content
    assert '"?date=2027-02-26"' in content and '"?date=2027-03-12"' in content  # ± 7 days
    assert "data-row=" not in content and "map-mark" not in content  # no van to place here
    assert "window.print()" in content
    assert reverse("storage:booking_find") in content  # placing a van is the other page
    assert 'aria-current="page"' in content and ">Planning<" in content


def test_warehouse_map_page_defaults_to_today_and_is_linked_from_planning(admin_client):
    response = admin_client.get(reverse("storage:planning_map"), {"date": "pas une date"})
    assert response.context["day"] == response.context["end"] == services.today()
    content = admin_client.get(reverse("storage:planning")).content.decode()
    assert reverse("storage:planning_map") in content


def test_warehouse_map_page_over_a_range_of_dates(admin_client):
    row = make_row("R01")
    make_booking(row, 1, MAR_1, periods=1, length="6.00")
    make_booking(row, 1, D(2027, 3, 15), periods=1, length="8.00")
    url = reverse("storage:planning_map")
    response = admin_client.get(url, {"date": "2027-03-01", "au": "2027-03-31"})
    content = response.content.decode()
    assert "Du 01/03/2027 au 31/03/2027 : 2 véhicules présents à un moment" in content
    assert response.context["map"].end == D(2027, 3, 31)
    # The 7-day buttons keep the length of the range.
    assert '"?date=2027-02-22&amp;au=2027-03-24"' in content
    assert '"?date=2027-03-08&amp;au=2027-04-07"' in content


@pytest.mark.parametrize(
    ("end", "message"),
    [("2027-02-01", "antérieure"), ("2028-06-01", "un an au maximum")],
)
def test_warehouse_map_page_refuses_bad_ranges(admin_client, end, message):
    url = reverse("storage:planning_map")
    response = admin_client.get(url, {"date": "2027-03-01", "au": end})
    assert message in response.content.decode()
    assert response.context["end"] == D(2027, 3, 1)  # one day shown instead


def test_warehouse_map_page_highlights_boxed_in_vehicles():
    row = make_row("R01")
    deep = make_booking(row, 2, MAR_1, periods=1, vehicle=make_vehicle(plate="AB-123"))
    aisle = make_booking(row, 1, MAR_1, periods=2, vehicle=make_vehicle(plate="XY-987"))
    in_march = build_map(MAR_1, D(2027, 3, 31), with_blockings=True)
    r = map_row(in_march, row)
    [plan] = r.move_plans
    assert plan.booking == deep and plan.blockers == [aisle]
    assert "Pour sortir AB-123 (position 2) le 14/03/2027 : déplacer d'abord XY-987" in (
        plan.as_text()
    )
    blocked = {v.booking: v.blocked for p in r.positions for v in p.vehicles}
    assert blocked == {aisle: False, deep: True}
    # Outside the dates of the exit, nothing to report.
    assert map_row(build_map(D(2027, 3, 1), with_blockings=True), row).move_plans == []


def test_warehouse_map_page_lists_the_moves(admin_client):
    row = make_row("R01")
    make_booking(row, 2, MAR_1, periods=1, vehicle=make_vehicle(plate="AB-123"))
    make_booking(row, 1, MAR_1, periods=2, vehicle=make_vehicle(plate="XY-987"))
    url = reverse("storage:planning_map")
    content = admin_client.get(url, {"date": "2027-03-01", "au": "2027-03-31"}).content.decode()
    assert "1 blocage en R01" in content and "status-reserved partial blocked" in content
    assert "Pour sortir AB-123 (position 2) le 14/03/2027" in content


# --- "Trouver un emplacement": placing a van for a booking ------------------------------


def test_find_page_is_reached_from_the_bookings(admin_client):
    content = admin_client.get(reverse("storage:booking_list")).content.decode()
    assert reverse("storage:booking_find") in content
    response = admin_client.get(reverse("storage:booking_find"))
    assert "<h1>Trouver un emplacement</h1>" in response.content.decode()
    assert "map" not in response.context  # nothing searched yet
    assert 'aria-current="page"' in response.content.decode()


def test_find_a_place_for_a_length(admin_client):
    row = make_row("R01")
    make_booking(row, 1, MAR_1, periods=1, length="8.00")
    full = make_row("R02")
    make_booking(full, 1, MAR_1, periods=1, length="8.00")
    make_booking(full, 2, MAR_1, periods=1, length="7.50")
    roomy = make_row("R03")
    params = {"date": "2027-03-01", "periodes": "2", "longueur": "7,40"}
    response = admin_client.get(reverse("storage:booking_find"), params)
    content = response.content.decode()
    assert "du 01/03/2027 au 28/03/2027" in content and "un véhicule de 7,40" in content
    # Ranked list first: the tighter fit (R01) before the empty row.
    assert [(s.row, s.position) for s in response.context["best"]] == [(row, 2), (roomy, 1)]
    assert content.count("Réserver ici") == 2
    rows = {r.row.code: r for r in response.context["map"].rows}
    assert rows["R01"].status == RowStatus.FITS and rows["R02"].status == RowStatus.FULL
    booking_link = (
        f"{reverse('storage:booking_create')}?rangee={row.pk}&amp;position=2"
        "&amp;debut=2027-03-01&amp;periodes=2"
    )
    assert booking_link in content
    assert f"rangee={full.pk}&amp;position" not in content  # no link where it does not fit


def test_find_a_place_for_a_registered_vehicle(admin_client):
    row = make_row("R01")
    vehicle = make_vehicle(length_m=Decimal("7.00"))
    params = {"date": "2027-03-01", "periodes": "1", "vehicule": vehicle.pk, "longueur": "3"}
    response = admin_client.get(reverse("storage:booking_find"), params)
    assert response.context["map"].vehicle == vehicle  # the vehicle wins over the length
    expected = (
        f"rangee={row.pk}&amp;position=1&amp;debut=2027-03-01&amp;periodes=1"
        f"&amp;vehicule={vehicle.pk}"
    )
    assert expected in response.content.decode()


def test_find_explains_the_moves(admin_client):
    row = make_row("R01")
    aisle = make_vehicle(plate="XY-987", length_m=Decimal("5.00"))
    make_booking(row, 1, MAR_1, periods=3, vehicle=aisle)
    for position in (2, 3):
        make_booking(row, position, MAR_1, periods=3, length="1.00")
    params = {"date": "2027-03-01", "periodes": "1", "longueur": "7"}
    content = admin_client.get(reverse("storage:booking_find"), params).content.decode()
    assert "Déplacements nécessaires en R01" in content and "gêné par XY-987" in content
    assert "Pour sortir le nouveau véhicule (position 4)" in content


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"date": "2027-03-01", "longueur": "7,4"}, "Indiquez le nombre de périodes"),
        ({"date": "2027-03-01", "periodes": "1"}, "Indiquez la longueur du véhicule"),
        ({"date": "2027-03-01", "periodes": "1", "longueur": "abc"}, "Longueur invalide"),
        ({"date": "2027-03-01", "periodes": "1", "longueur": "25"}, "Longueur invalide"),
        ({"date": "2027-03-01", "periodes": "1", "longueur": "nan"}, "Longueur invalide"),
        ({"date": "2027-03-01", "periodes": "0", "longueur": "7"}, "Indiquez le nombre de"),
    ],
)
def test_find_reports_missing_or_bad_values(admin_client, params, message):
    response = admin_client.get(reverse("storage:booking_find"), params)
    assert message in response.content.decode()
    assert "map" not in response.context


def test_find_for_an_already_booked_vehicle(admin_client):
    booking = make_booking(make_row("R01"), 1, MAR_1, periods=1)
    params = {"date": "2027-03-01", "periodes": "1", "vehicule": booking.vehicle_id}
    content = admin_client.get(reverse("storage:booking_find"), params).content.decode()
    assert "est déjà réservé sur cette période" in content
    assert "Réserver ici" not in content


def test_booking_form_prefilled_from_the_search(admin_client):
    row, vehicle = make_row("R04"), make_vehicle()
    params = {
        "rangee": row.pk,
        "position": "3",
        "debut": "2027-03-01",
        "periodes": "4",
        "vehicule": vehicle.pk,
    }
    form = admin_client.get(reverse("storage:booking_create"), params).context["form"]
    assert form.initial["position"] == "3" and form.initial["periods"] == "4"
    assert form.initial["vehicle"] == str(vehicle.pk)
    assert form.initial["client"] == vehicle.client_id
