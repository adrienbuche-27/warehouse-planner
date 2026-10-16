"""M4: planning grid (CLAUDE.md, section 7.2)."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from storage import planning
from storage.models import BookingStatus
from tests.factories import FLAT_PRICE, make_booking, make_row, make_vehicle, set_settings

pytestmark = pytest.mark.django_db

D = datetime.date
MON = D(2027, 3, 1)  # a Monday


@pytest.fixture(autouse=True)
def demo_settings():
    set_settings(
        **FLAT_PRICE,
        default_row_length_m=Decimal("16.00"),
        vehicle_gap_m=Decimal("0.50"),
    )


def test_monday_of():
    assert planning.monday_of(D(2027, 3, 4)) == MON
    assert planning.monday_of(MON) == MON
    assert planning.monday_of(D(2027, 3, 7)) == MON  # Sunday


def test_windows_are_consecutive_periods():
    windows = planning.windows(MON, 13, 14)
    assert len(windows) == 13
    assert windows[0] == (MON, D(2027, 3, 14))
    assert windows[1] == (D(2027, 3, 15), D(2027, 3, 28))
    assert windows[-1][1] == D(2027, 8, 29)


@pytest.mark.parametrize(
    ("used", "level"),
    [
        ("0", "ok"),
        ("11.19", "ok"),
        ("11.2", "warn"),
        ("15.2", "warn"),
        ("15.21", "danger"),
        ("16", "danger"),
    ],
)
def test_occupancy_colour_thresholds(used, level):
    # 16 m row: 70 % = 11,2 m, 95 % = 15,2 m.
    assert planning.occupancy_level(Decimal(used), Decimal("16")) == level


def test_grid_cells_show_peak_occupancy_per_window():
    row = make_row("R01")
    make_booking(row, 1, MON, periods=2, length="8")  # 1–28 March
    make_booking(row, 2, D(2027, 3, 20), periods=1, length="5")  # 20 March – 2 April
    grid = planning.build_grid(MON, count=3)
    cells = grid.rows[0].cells
    assert [cell.peak_m for cell in cells] == [Decimal("8"), Decimal("13.5"), Decimal("5")]
    assert [cell.level for cell in cells] == ["ok", "warn", "ok"]
    assert cells[1].free_m == Decimal("2.5")
    assert cells[1].vehicle_count == 2


def test_grid_ignores_cancelled_bookings_and_inactive_rows():
    row = make_row("R01", display_order=1)
    make_row("R02", display_order=2, is_active=False)
    make_booking(row, 1, MON, length="8", status=BookingStatus.CANCELLED)
    grid = planning.build_grid(MON, count=1)
    assert [r.row.code for r in grid.rows] == ["R01"]
    assert grid.rows[0].cells[0].peak_m == 0


def test_blocking_warning_appears_in_the_window_of_the_blocked_exit():
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    make_booking(row, 2, MON, periods=1, length="6")  # leaves 14 March...
    make_booking(row, 1, MON, periods=3, length="6")  # ...but position 1 stays until 11 April
    grid = planning.build_grid(MON, count=3)
    assert [cell.has_blocking for cell in grid.rows[0].cells] == [True, False, False]


def test_blocking_warning_for_blocked_entry_only_while_reserved():
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    make_booking(row, 1, MON, periods=4, length="6")
    deep = make_booking(row, 2, D(2027, 3, 20), periods=3, length="6")  # enters behind it
    grid = planning.build_grid(MON, count=4)
    assert [cell.has_blocking for cell in grid.rows[0].cells] == [False, True, False, False]
    deep.status = BookingStatus.STORED
    deep.save()
    grid = planning.build_grid(MON, count=4)
    assert not any(cell.has_blocking for cell in grid.rows[0].cells)


def test_min_free_filter_keeps_rows_with_enough_space_somewhere():
    almost_full = make_row("R01", display_order=1)
    roomy = make_row("R02", display_order=2)
    make_booking(almost_full, 1, MON, periods=2, length="8")
    make_booking(almost_full, 2, MON, periods=2, length="7")
    make_booking(roomy, 1, MON, periods=1, length="5")
    grid = planning.build_grid(MON, count=2, min_free_m=Decimal("8"))
    assert [r.row.code for r in grid.rows] == ["R02"]
    grid = planning.build_grid(MON, count=3, min_free_m=Decimal("8"))
    assert [r.row.code for r in grid.rows] == ["R01", "R02"]  # R01 empties in window 3


def test_cell_details_by_position_with_move_plans():
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    deep = make_booking(row, 2, MON, periods=1, vehicle=make_vehicle(plate="AB-123-CD"))
    front = make_booking(row, 1, MON, periods=3, vehicle=make_vehicle(plate="XY-987-ZZ"))
    make_booking(row, 3, D(2027, 6, 1), periods=1)  # another window
    details = planning.cell_details(row, MON, D(2027, 3, 14))
    assert [item.booking for item in details] == [front, deep]
    assert details[1].plans[0].blockers == [front]


# --- Views -------------------------------------------------------------------


def test_planning_requires_login(client):
    assert client.get(reverse("storage:planning")).status_code == 302


def test_planning_page(admin_client):
    row = make_row("R01")
    make_booking(row, 1, MON, length="8")
    make_booking(row, 2, MON, length="5")
    response = admin_client.get(reverse("storage:planning"), {"debut": "2027-03-03"})
    assert response.status_code == 200
    grid = response.context["grid"]
    assert grid.start == MON  # snapped to the Monday
    assert len(grid.windows) == 13
    content = response.content.decode()
    assert "13,5 / 16 m" in content
    assert 'aria-current="page">Planning' in content
    assert response.context["nav"]["back"] == D(2027, 2, 15)
    assert response.context["nav"]["page_forward"] == D(2027, 8, 30)


def test_planning_defaults_to_this_monday(admin_client):
    from storage.services import today

    response = admin_client.get(reverse("storage:planning"))
    assert response.context["grid"].start == planning.monday_of(today())


def test_planning_free_space_filter(admin_client):
    full = make_row("R01", display_order=1)
    make_row("R02", display_order=2)
    for position, length in [(1, "8"), (2, "7.5")]:
        make_booking(full, position, MON, periods=14, length=length)
    response = admin_client.get(
        reverse("storage:planning"), {"debut": "2027-03-01", "libre": "8,5"}
    )
    assert [r.row.code for r in response.context["grid"].rows] == ["R02"]
    content = response.content.decode()
    assert 'value="8.5"' in content
    assert "dimmed" not in content  # R02 is empty: every window has 8,5 m free

    # R03 is full during the first window only: it stays listed, with that window dimmed.
    busy_once = make_row("R03", display_order=3)
    make_booking(busy_once, 1, MON, periods=1, length="8")
    make_booking(busy_once, 2, MON, periods=1, length="7.5")
    response = admin_client.get(reverse("storage:planning"), {"debut": "2027-03-01", "libre": "1"})
    assert [r.row.code for r in response.context["grid"].rows] == ["R02", "R03"]
    assert response.content.decode().count(" dimmed") == 1


def test_planning_cell_panel(admin_client):
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    make_booking(row, 2, MON, periods=1, vehicle=make_vehicle(plate="AB-123-CD"))
    make_booking(row, 1, MON, periods=3, vehicle=make_vehicle(plate="XY-987-ZZ"))
    url = reverse("storage:planning_cell", args=[row.pk, "2027-03-01"])
    content = admin_client.get(url).content.decode()
    assert "R01 · du 01/03/2027 au 14/03/2027" in content
    assert content.index("XY-987-ZZ") < content.index("AB-123-CD")  # by position
    assert "Pour sortir <strong>AB-123-CD</strong>" in content
    assert f"?rangee={row.pk}&debut=2027-03-01" in content


def test_planning_cell_new_booking_starts_today_for_a_window_already_begun(admin_client):
    from storage.services import today

    row = make_row("R01")
    window_start = planning.monday_of(today()) - datetime.timedelta(days=7)
    url = reverse("storage:planning_cell", args=[row.pk, window_start.isoformat()])
    response = admin_client.get(url)
    assert response.context["new_booking_start"] == today()


def test_planning_cell_bad_date_is_404(admin_client):
    row = make_row("R01")
    assert (
        admin_client.get(
            reverse("storage:planning_cell", args=[row.pk, "pas-une-date"])
        ).status_code
        == 404
    )
