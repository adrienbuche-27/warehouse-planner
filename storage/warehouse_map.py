"""Warehouse map: a top-down view of the rows (backlog #4).

Each active row is a horizontal strip, in display order, with the aisle on the left. Its
vehicles are drawn one after another by position (1 = closest to the aisle), each sized to
its length. The map is shown:

- in the booking form, for the dates of the booking: every vehicle present at some point
  of the stay is drawn (those present only part of the time are marked `partial`), the free
  metres are those at the busiest moment, and each row says whether the new vehicle fits
  there (see `RowStatus`) and at which position;
- on the "Trouver un emplacement" page, the same for a van not booked yet (or known only by
  its length), to choose where to book it;
- on the "Plan de l'entrepôt" page (space management), for one day or a range of dates, with
  the vehicles boxed in when entering or leaving during those dates and their move plans.

Everything comes from one query on the bookings plus `suggest_placements`, then is computed
in memory.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from clients.models import Vehicle
from core.models import AppSettings
from storage.models import Booking, BookingStatus, Row
from storage.planning import occupancy_level
from storage.services import (
    ENTRY,
    EXIT,
    MovePlan,
    Slot,
    find_blockers,
    occupancy_timeline,
    placement_warnings,
    suggest_placements,
)

STARRED_SUGGESTIONS = 5  # the rows of the 5 best suggestions get a star, as in the form


class RowStatus:
    """Whether the vehicle being booked can go in a row (booking form only)."""

    FITS = "fits"  # ✓ fits without moving anyone
    CONFLICT = "conflict"  # ⚠ fits, but vehicles will have to be moved (move plan)
    FULL = "full"  # ✗ not enough room at any position


def _percent(part: Decimal, whole: Decimal) -> str:
    """Share as a CSS percentage with a dot ("43.75"), whatever the display language."""
    if not whole:
        return "0"
    return f"{min(Decimal(part) * 100 / whole, Decimal(100)):.2f}"


@dataclass
class MapVehicle:
    booking: Booking
    width: str  # CSS percentage of its position's width
    partial: bool  # present only during part of the shown dates
    blocked: bool = False  # boxed in when entering or leaving during the shown dates


@dataclass
class MapPosition:
    """One position of a row. Over several weeks, a position can be used by several vehicles
    one after another: they are stacked, in date order, in the width of the longest one."""

    position: int
    width: str  # CSS percentage of the row length
    vehicles: list[MapVehicle]


@dataclass
class MapRow:
    row: Row
    length_m: Decimal
    width: str  # CSS percentage of the longest row, so shorter rows look shorter
    peak_m: Decimal
    positions: list[MapPosition] = field(default_factory=list)
    # "Plan de l'entrepôt" only: what to move for the boxed-in vehicles, in date order.
    move_plans: list[MovePlan] = field(default_factory=list)
    # Booking form and "Trouver un emplacement" only:
    status: str = ""
    starred: bool = False
    position: int | None = None  # best position for the new vehicle in this row
    warnings: list[str] = field(default_factory=list)  # move plan when status is CONFLICT

    @property
    def free_m(self) -> Decimal:
        return max(self.length_m - self.peak_m, Decimal("0"))

    @property
    def level(self) -> str:
        return occupancy_level(self.peak_m, self.length_m)

    @property
    def can_pick(self) -> bool:
        return self.status in (RowStatus.FITS, RowStatus.CONFLICT)


@dataclass
class WarehouseMap:
    start: datetime.date
    end: datetime.date
    rows: list[MapRow]
    vehicle: Vehicle | None = None
    # With a vehicle: every place where it fits, best first (storage.services.Suggestion).
    suggestions: list = field(default_factory=list)

    @property
    def vehicle_count(self) -> int:
        return sum(len(p.vehicles) for row in self.rows for p in row.positions)

    @property
    def total_length_m(self) -> Decimal:
        return sum((row.length_m for row in self.rows), Decimal("0"))

    @property
    def total_free_m(self) -> Decimal:
        return sum((row.free_m for row in self.rows), Decimal("0"))

    @property
    def occupancy_percent(self) -> int:
        if not self.total_length_m:
            return 0
        used = self.total_length_m - self.total_free_m
        return round(used * 100 / self.total_length_m)


def planned_vehicle(length_m: Decimal) -> Vehicle:
    """A van known only by its length (not registered yet), to see where it would fit.
    Never saved: its "plate" is the wording used in the move plans."""
    return Vehicle(plate="le nouveau véhicule", length_m=length_m)


def build_map(
    start: datetime.date,
    end: datetime.date | None = None,
    vehicle: Vehicle | None = None,
    exclude_booking: Booking | None = None,
    with_blockings: bool = False,
) -> WarehouseMap:
    """The map for [start, end] (one day when `end` is omitted).

    With `vehicle` (booking form, "Trouver un emplacement"), each row also gets its status for
    that vehicle, its best position and, when vehicles must be moved, the move plan.
    `exclude_booking` is the booking being edited: it is left out, as in the fit check.
    With `with_blockings` ("Plan de l'entrepôt"), the vehicles boxed in during the dates are
    marked and each row lists their move plans.
    """
    end = end or start
    app_settings = AppSettings.load()
    gap = app_settings.vehicle_gap_m

    bookings = (
        Booking.objects.active()
        .filter(row__is_active=True)
        .overlapping(start, end)
        .select_related("vehicle__client")
    )
    if exclude_booking is not None and exclude_booking.pk:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    by_row = defaultdict(list)
    for booking in bookings:
        by_row[booking.row_id].append(booking)

    rows = list(Row.objects.filter(is_active=True))
    lengths = {row.pk: row.effective_length_for(app_settings) for row in rows}
    longest = max(lengths.values(), default=Decimal("0"))

    map_rows = []
    for row in rows:
        length = lengths[row.pk]
        row_bookings = sorted(by_row[row.pk], key=lambda b: (b.position, b.start_date))
        slots = [Slot.of(booking) for booking in row_bookings]
        peak = max(
            (used for _, _, used in occupancy_timeline(slots, start, end, gap)),
            default=Decimal("0"),
        )
        map_row = MapRow(
            row=row,
            length_m=length,
            width=_percent(length, longest),
            peak_m=peak,
            positions=_positions(row_bookings, length, start, end),
        )
        if with_blockings:
            _add_blockings(map_row, slots, start, end)
        map_rows.append(map_row)

    suggestions = []
    if vehicle is not None:
        suggestions = _add_statuses(map_rows, vehicle, start, end, exclude_booking)
    return WarehouseMap(
        start=start, end=end, rows=map_rows, vehicle=vehicle, suggestions=suggestions
    )


def _positions(row_bookings, row_length, start, end) -> list[MapPosition]:
    by_position = defaultdict(list)
    for booking in row_bookings:  # sorted by position, then date
        by_position[booking.position].append(booking)
    positions = []
    for position, bookings in by_position.items():
        widest = max(booking.vehicle.length_m for booking in bookings)
        vehicles = [
            MapVehicle(
                booking=booking,
                width=_percent(booking.vehicle.length_m, widest),
                partial=booking.start_date > start or booking.end_date < end,
            )
            for booking in bookings
        ]
        positions.append(MapPosition(position, _percent(widest, row_length), vehicles))
    return positions


def _add_blockings(map_row: MapRow, slots: list[Slot], start, end) -> None:
    """Entries and exits during [start, end] that are boxed in, with their move plans.

    The slots are all the active bookings of the row present during the dates, which includes
    every possible blocker (a blocker is present on the day of the entry or exit). A vehicle
    already in stock has no entry left to plan, as in `services.move_plans`.
    """
    plans = []
    for slot in slots:
        booking = slot.booking
        others = [other for other in slots if other is not slot]
        events = []
        if booking.status == BookingStatus.RESERVED and start <= booking.start_date <= end:
            events.append(ENTRY)
        if start <= booking.end_date <= end:
            events.append(EXIT)
        for event in events:
            blockers = [blocker.booking for blocker in find_blockers(slot, others, event)]
            if blockers:
                plans.append(MovePlan(booking, event, blockers))
    map_row.move_plans = sorted(plans, key=lambda plan: plan.date)
    blocked = {plan.booking.pk for plan in plans}
    for position in map_row.positions:
        for vehicle in position.vehicles:
            vehicle.blocked = vehicle.booking.pk in blocked


def _add_statuses(map_rows, vehicle, start, end, exclude_booking) -> list:
    """Row status, best position and move plan for the vehicle being booked. Returns the
    suggestions (every place where it fits, best first)."""
    suggestions = suggest_placements(vehicle, start, end, exclude_booking)
    starred = {s.row.pk for s in suggestions[:STARRED_SUGGESTIONS]}
    best = {}
    for suggestion in suggestions:  # best first: keep the first one of each row
        best.setdefault(suggestion.row.pk, suggestion)
    for map_row in map_rows:
        suggestion = best.get(map_row.row.pk)
        if suggestion is None:
            map_row.status = RowStatus.FULL
            continue
        map_row.position = suggestion.position
        map_row.starred = map_row.row.pk in starred
        if suggestion.conflict_count:
            map_row.status = RowStatus.CONFLICT
            map_row.warnings = placement_warnings(
                map_row.row, vehicle, start, end, suggestion.position, exclude_booking
            )
        else:
            map_row.status = RowStatus.FITS
    return suggestions
