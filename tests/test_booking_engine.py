"""M3: fit check, boxed-in detection, suggestions, dates and pricing (CLAUDE.md, section 11)."""

import datetime
from decimal import Decimal

import pytest

from core.models import VatRegime
from core.pricing import compute_totals, compute_vat
from storage import services
from storage.models import Booking, BookingStatus, compute_end_date
from tests.factories import BANDS_2M_12EUR, make_booking, make_row, make_vehicle, set_settings

pytestmark = pytest.mark.django_db

D = datetime.date
MAR_1 = D(2027, 3, 1)


def end_of(periods, start=MAR_1):
    return compute_end_date(start, periods, 14)


# --- Fit check ---------------------------------------------------------------


@pytest.fixture
def row16():
    set_settings(default_row_length_m=Decimal("16.00"), vehicle_gap_m=Decimal("0.50"))
    return make_row("R01")


def test_two_8m_vehicles_fit_in_16m_without_gap(row16):
    set_settings(vehicle_gap_m=Decimal("0"))
    make_booking(row16, 1, MAR_1, length="8")
    result = services.check_fit(row16, make_vehicle(length_m=Decimal("8")), MAR_1, end_of(1), 2)
    assert result.ok
    assert result.peak_occupancy_m == Decimal("16")
    assert result.free_m_at_peak == Decimal("0")


def test_two_8m_vehicles_do_not_fit_with_half_metre_gap(row16):
    first = make_booking(row16, 1, MAR_1, length="8")
    result = services.check_fit(row16, make_vehicle(length_m=Decimal("8")), MAR_1, end_of(1), 2)
    assert not result.ok
    assert result.peak_occupancy_m == Decimal("16.5")
    assert result.free_m_at_peak == Decimal("-0.5")
    assert result.length_conflicts == [first]


def test_three_5m_vehicles_with_gap_fill_exactly_16m(row16):
    make_booking(row16, 1, MAR_1, length="5")
    make_booking(row16, 2, MAR_1, length="5")
    result = services.check_fit(row16, make_vehicle(length_m=Decimal("5")), MAR_1, end_of(1), 3)
    assert result.ok
    assert result.peak_occupancy_m == Decimal("16.0")


def test_non_overlapping_dates_do_not_conflict(row16):
    make_booking(row16, 1, MAR_1, periods=1, length="8")
    make_booking(row16, 2, MAR_1, periods=1, length="8")
    later = end_of(1) + datetime.timedelta(days=1)
    result = services.check_fit(
        row16, make_vehicle(length_m=Decimal("8")), later, end_of(1, later), 1
    )
    assert result.ok
    assert result.peak_occupancy_m == Decimal("8")


def test_occupancy_changing_mid_interval_is_detected(row16):
    # A 7 m vehicle arrives in the middle of the new 2-period booking.
    make_booking(row16, 1, MAR_1, length="8")  # 1–14 March
    make_booking(row16, 3, D(2027, 3, 20), length="7")  # 20 March – 2 April
    new_vehicle = make_vehicle(length_m=Decimal("3"))
    # 1–28 March: day 1 has 8 + 3 (+gap), day 20 has 7 + 3 (+gap): both fit.
    assert services.check_fit(row16, new_vehicle, MAR_1, end_of(2), 2).ok
    # A 9 m vehicle fits from 15 to 19 March only: it overflows on 1 March and on 20 March.
    big = make_vehicle(length_m=Decimal("9"))
    result = services.check_fit(row16, big, D(2027, 3, 15), D(2027, 3, 25), 2)
    assert not result.ok
    assert result.peak_occupancy_m == Decimal("16.5")
    assert services.check_fit(row16, big, D(2027, 3, 15), D(2027, 3, 19), 2).ok


def test_same_position_overlap_is_rejected(row16):
    existing = make_booking(row16, 1, MAR_1, length="5")
    result = services.check_fit(
        row16, make_vehicle(length_m=Decimal("5")), D(2027, 3, 10), end_of(1, D(2027, 3, 10)), 1
    )
    assert not result.ok
    assert result.position_conflicts == [existing]
    assert result.length_conflicts == []


def test_cancelled_and_ended_bookings_free_their_space(row16):
    make_booking(row16, 1, MAR_1, length="8", status=BookingStatus.CANCELLED)
    make_booking(row16, 2, MAR_1, length="8", status=BookingStatus.ENDED)
    result = services.check_fit(row16, make_vehicle(length_m=Decimal("8")), MAR_1, end_of(1), 1)
    assert result.ok
    assert result.peak_occupancy_m == Decimal("8")


def test_exclude_booking_when_editing(row16):
    booking = make_booking(row16, 1, MAR_1, length="8")
    make_booking(row16, 2, MAR_1, length="7")
    # Without exclusion the booking would conflict with itself (same position, double length).
    assert not services.check_fit(row16, booking.vehicle, MAR_1, end_of(1), 1).ok
    result = services.check_fit(
        row16, booking.vehicle, MAR_1, end_of(1), 1, exclude_booking=booking
    )
    assert result.ok
    assert result.peak_occupancy_m == Decimal("15.5")


def test_same_vehicle_cannot_be_booked_twice_at_the_same_time(row16):
    other_row = make_row("R02")
    booking = make_booking(row16, 1, MAR_1, length="6")
    result = services.check_fit(
        other_row, booking.vehicle, D(2027, 3, 10), end_of(1, D(2027, 3, 10)), 1
    )
    assert not result.ok
    assert result.vehicle_conflicts == [booking]


# --- Boxed-in detection ------------------------------------------------------


@pytest.fixture
def row30():
    set_settings(default_row_length_m=Decimal("30.00"), vehicle_gap_m=Decimal("0.50"))
    return make_row("R01")


def test_exit_blocked_by_vehicle_closer_to_aisle_staying_longer(row30):
    deep = make_booking(row30, 2, MAR_1, periods=1, length="6")
    front = make_booking(row30, 1, MAR_1, periods=2, length="6")
    assert services.get_blockers(deep, "exit") == [front]
    assert services.get_blockers(front, "exit") == []


def test_exit_not_blocked_when_front_vehicle_leaves_first(row30):
    deep = make_booking(row30, 2, MAR_1, periods=2, length="6")
    make_booking(row30, 1, MAR_1, periods=1, length="6")
    assert services.get_blockers(deep, "exit") == []


def test_exit_not_blocked_by_vehicle_leaving_the_same_day(row30):
    deep = make_booking(row30, 2, MAR_1, periods=1, length="6")
    make_booking(row30, 1, MAR_1, periods=1, length="6")
    assert services.get_blockers(deep, "exit") == []


def test_exit_blocked_by_vehicle_arriving_on_exit_day(row30):
    deep = make_booking(row30, 2, MAR_1, periods=1, length="6")  # leaves 14 March
    front = make_booking(row30, 1, D(2027, 3, 14), periods=1, length="6")
    assert services.get_blockers(deep, "exit") == [front]


def test_entry_blocked_by_vehicle_already_closer_to_aisle(row30):
    front = make_booking(row30, 1, MAR_1, periods=2, length="6")
    deep = make_booking(row30, 2, D(2027, 3, 10), periods=1, length="6")
    assert services.get_blockers(deep, "entry") == [front]
    assert services.get_blockers(front, "entry") == []


def test_entry_not_blocked_when_arriving_the_same_day(row30):
    make_booking(row30, 1, MAR_1, periods=2, length="6")
    deep = make_booking(row30, 2, MAR_1, periods=1, length="6")
    assert services.get_blockers(deep, "entry") == []


def test_blockers_sorted_by_position_closest_to_aisle_first(row30):
    deep = make_booking(row30, 3, MAR_1, periods=1, length="6")
    second = make_booking(row30, 2, MAR_1, periods=3, length="6")
    first = make_booking(row30, 1, MAR_1, periods=2, length="6")
    assert services.get_blockers(deep, "exit") == [first, second]


def test_cancelled_and_ended_bookings_never_block(row30):
    deep = make_booking(row30, 3, MAR_1, periods=1, length="6")
    make_booking(row30, 1, MAR_1, periods=2, length="6", status=BookingStatus.CANCELLED)
    make_booking(row30, 2, MAR_1, periods=2, length="6", status=BookingStatus.ENDED)
    assert services.get_blockers(deep, "exit") == []


def test_move_plan_wording(row30):
    deep = make_booking(row30, 3, MAR_1, periods=1, vehicle=make_vehicle(plate="AB-123-CD"))
    make_booking(row30, 1, MAR_1, periods=2, vehicle=make_vehicle(plate="XY-987-ZZ"))
    make_booking(row30, 2, MAR_1, periods=3, vehicle=make_vehicle(plate="QR-456-ST"))
    plans = services.move_plans(deep)
    assert len(plans) == 1
    assert plans[0].as_text() == (
        "Pour sortir AB-123-CD (position 3) le 14/03/2027 : déplacer d'abord "
        "XY-987-ZZ (pos. 1), puis QR-456-ST (pos. 2). Les replacer ensuite dans l'ordre inverse."
    )


# --- Suggestions -------------------------------------------------------------


def test_suggestions_prefer_no_conflicts_over_tighter_fit():
    set_settings(default_row_length_m=Decimal("16.00"), vehicle_gap_m=Decimal("0.50"))
    tight = make_row("R01", display_order=1)
    roomy = make_row("R02", display_order=2)
    # R01: a long stay at position 1 would block a short stay placed behind it,
    # and a short stay in front of it would block it.
    make_booking(tight, 1, MAR_1, periods=6, length="7")
    new_vehicle = make_vehicle(length_m=Decimal("7"))
    suggestions = services.suggest_placements(new_vehicle, MAR_1, end_of(1))
    best = suggestions[0]
    assert (best.row, best.position, best.conflict_count) == (roomy, 1, 0)
    r01 = [s for s in suggestions if s.row == tight]
    assert r01 and all(s.conflict_count > 0 for s in r01)


def test_suggestions_prefer_tighter_fit_when_no_conflicts():
    set_settings(default_row_length_m=Decimal("16.00"), vehicle_gap_m=Decimal("0.50"))
    empty = make_row("R01", display_order=1)
    partly_full = make_row("R02", display_order=2)
    # Same dates: no blocking either way, but R02 leaves less wasted space.
    make_booking(partly_full, 1, MAR_1, periods=1, length="8")
    suggestions = services.suggest_placements(make_vehicle(length_m=Decimal("7")), MAR_1, end_of(1))
    assert [(s.row, s.position) for s in suggestions[:2]] == [(partly_full, 2), (empty, 1)]
    assert suggestions[0].wasted_m == Decimal("0.5")


def test_suggestions_put_longer_stays_deeper():
    set_settings(default_row_length_m=Decimal("16.00"), vehicle_gap_m=Decimal("0.50"))
    row = make_row("R01")
    make_booking(row, 1, MAR_1, periods=1, length="7")
    # Leaving later than the vehicle at position 1, so it must go behind it... but position 1
    # is taken; the only valid spot is 2, which blocks nobody since it leaves later.
    suggestions = services.suggest_placements(make_vehicle(length_m=Decimal("7")), MAR_1, end_of(3))
    assert suggestions[0].position == 2
    assert suggestions[0].conflict_count == 0


def test_suggestions_skip_inactive_rows_and_full_rows():
    set_settings(default_row_length_m=Decimal("16.00"), vehicle_gap_m=Decimal("0.50"))
    make_row("R01", is_active=False)
    full = make_row("R02")
    make_booking(full, 1, MAR_1, length="8")
    make_booking(full, 2, MAR_1, length="7.5")
    assert services.suggest_placements(make_vehicle(length_m=Decimal("6")), MAR_1, end_of(1)) == []


def test_no_suggestions_for_a_vehicle_already_booked():
    set_settings(default_row_length_m=Decimal("16.00"))
    row = make_row("R01")
    make_row("R02")
    booking = make_booking(row, 1, MAR_1, length="6")
    assert services.suggest_placements(booking.vehicle, MAR_1, end_of(1)) == []
    assert services.suggest_placements(booking.vehicle, MAR_1, end_of(1), exclude_booking=booking)


# --- Dates and pricing -------------------------------------------------------


def test_end_date_computation():
    assert compute_end_date(D(2027, 3, 1), 1, 14) == D(2027, 3, 14)
    assert compute_end_date(D(2027, 3, 1), 2, 14) == D(2027, 3, 28)
    assert compute_end_date(D(2027, 12, 25), 1, 14) == D(2028, 1, 7)


def test_booking_stores_end_date():
    booking = make_booking(make_row(), 1, D(2027, 2, 20), periods=2)
    booking.refresh_from_db()
    assert booking.end_date == D(2027, 3, 19)  # 28 days, through the end of February


def test_price_snapshot_is_unaffected_by_later_settings_changes():
    set_settings(**BANDS_2M_12EUR, vat_rate=Decimal("21.00"))
    booking = make_booking(make_row(), 1, MAR_1, periods=3, length="7.40")
    set_settings(
        price_per_band=Decimal("20.00"),
        band_length_m=Decimal("3.00"),
        vat_regime=VatRegime.FRANCHISE,
    )
    booking = Booking.objects.get(pk=booking.pk)
    booking.notes = "modifiée"
    booking.save()
    assert (booking.band_length_m, booking.price_per_band) == (Decimal("2.00"), Decimal("12.00"))
    assert booking.band_count == 4
    assert booking.price_per_period == Decimal("48.00")
    assert booking.vat_regime == VatRegime.STANDARD
    assert booking.totals.excl_vat == Decimal("144.00")
    assert booking.totals.vat == Decimal("30.24")
    assert booking.totals.incl_vat == Decimal("174.24")


def test_booking_requires_a_price_in_settings():
    from django.core.exceptions import ValidationError

    set_settings(price_per_band=None)
    with pytest.raises(ValidationError, match="prix par tranche"):
        Booking.objects.create(
            vehicle=make_vehicle(), row=make_row(), position=1, start_date=MAR_1, periods=1
        )


def test_vat_rounding_half_up():
    assert compute_vat(Decimal("12.50"), VatRegime.STANDARD, Decimal("21")) == Decimal("2.63")
    assert compute_vat(Decimal("45.55"), VatRegime.STANDARD, Decimal("21")) == Decimal("9.57")
    assert compute_vat(Decimal("10.10"), VatRegime.STANDARD, Decimal("6")) == Decimal("0.61")
    totals = compute_totals(3, Decimal("12.50"), VatRegime.STANDARD, Decimal("21"))
    assert (totals.excl_vat, totals.vat, totals.incl_vat) == (
        Decimal("37.50"),
        Decimal("7.88"),
        Decimal("45.38"),
    )


def test_franchise_regime_charges_no_vat():
    totals = compute_totals(2, Decimal("45.00"), VatRegime.FRANCHISE, Decimal("21"))
    assert totals.vat == Decimal("0.00")
    assert totals.incl_vat == totals.excl_vat == Decimal("90.00")


def test_move_plans_skip_entry_once_the_vehicle_is_in_stock(row30):
    make_booking(row30, 1, MAR_1, periods=3, length="6")
    deep = make_booking(row30, 2, D(2027, 3, 10), periods=1, length="6")
    assert [plan.event for plan in services.move_plans(deep)] == ["entry", "exit"]
    deep.status = BookingStatus.STORED
    deep.save()
    assert [plan.event for plan in services.move_plans(deep)] == ["exit"]


# --- Settings changes (section 6.5) ------------------------------------------


def test_shrinking_a_row_reports_affected_bookings(row16):
    today = services.today()
    first = make_booking(row16, 1, today, length="8")
    second = make_booking(row16, 2, today, length="7")
    make_booking(row16, 3, today - datetime.timedelta(days=60), length="8")  # already over
    assert services.bookings_not_fitting() == []
    assert services.bookings_not_fitting(row_lengths={row16.pk: Decimal("15.50")}) == []
    assert services.bookings_not_fitting(row_lengths={row16.pk: Decimal("15.00")}) == [
        first,
        second,
    ]


def test_lower_default_length_or_bigger_gap_reports_affected_bookings(row16):
    other = make_row("R02", length_override_m=Decimal("20"))
    today = services.today()
    a = make_booking(row16, 1, today, length="8")
    b = make_booking(row16, 2, today, length="7.5")
    make_booking(other, 1, today, length="8")
    make_booking(other, 2, today, length="7.5")
    assert services.bookings_not_fitting(default_row_length=Decimal("15")) == [a, b]
    assert services.bookings_not_fitting(gap=Decimal("0.60")) == [a, b]
    assert services.bookings_not_fitting(gap=Decimal("0.40")) == []


def test_row_with_current_or_future_bookings_cannot_be_deactivated(row16):
    today = services.today()
    assert services.bookings_preventing_deactivation(row16) == []
    make_booking(row16, 1, today - datetime.timedelta(days=60), length="6")  # ended already
    assert services.bookings_preventing_deactivation(row16) == []
    future = make_booking(row16, 2, today + datetime.timedelta(days=30), length="6")
    assert services.bookings_preventing_deactivation(row16) == [future]


# --- Status changes and extension --------------------------------------------


def test_status_changes(row16):
    booking = make_booking(row16, 1, MAR_1)
    with pytest.raises(services.BookingActionError):
        services.mark_ended(booking, MAR_1)
    services.mark_stored(booking, D(2027, 3, 2))
    assert (booking.status, booking.actual_check_in) == (BookingStatus.STORED, D(2027, 3, 2))
    with pytest.raises(services.BookingActionError):
        services.cancel(booking)
    with pytest.raises(services.BookingActionError, match="antérieure"):
        services.mark_ended(booking, D(2027, 3, 1))
    services.mark_ended(booking, D(2027, 3, 12))
    assert (booking.status, booking.actual_check_out) == (BookingStatus.ENDED, D(2027, 3, 12))


def test_cancel_reserved_booking(row16):
    booking = make_booking(row16, 1, MAR_1)
    services.cancel(booking)
    assert booking.status == BookingStatus.CANCELLED


def test_extend_recomputes_end_date_and_keeps_price(row16):
    booking = make_booking(row16, 1, MAR_1, periods=1)
    set_settings(price_per_band=Decimal("99.00"))
    check = services.extend(booking, 2)
    assert check.applied
    booking.refresh_from_db()
    assert booking.periods == 3
    assert booking.end_date == D(2027, 4, 11)
    assert booking.price_per_period == Decimal("45.00")


def test_extend_refused_when_it_no_longer_fits(row16):
    booking = make_booking(row16, 1, MAR_1, periods=1, length="8")
    make_booking(row16, 2, MAR_1 + datetime.timedelta(days=14), periods=1, length="8")
    with pytest.raises(services.BookingActionError, match="ne tient plus"):
        services.extend(booking, 1)
    booking.refresh_from_db()
    assert booking.periods == 1


def test_extend_needs_confirmation_when_it_creates_blocking(row30):
    deep = make_booking(row30, 2, MAR_1, periods=2, length="6")
    front = make_booking(row30, 1, MAR_1, periods=1, length="6")
    check = services.extend(front, 2)  # front would now leave after the vehicle behind it
    assert not check.applied
    assert check.newly_blocked == [deep]
    front.refresh_from_db()
    assert front.periods == 1
    assert services.extend(front, 2, confirmed=True).applied
