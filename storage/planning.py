"""Planning grid (CLAUDE.md, section 7.2): rows × 2-week windows.

Each cell gives the peak occupancy of the row during the window and whether a vehicle of
that row has a blocked entry or exit during the window. Everything is computed from one
query on the bookings, then in memory.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from core.models import AppSettings
from storage.models import Booking, BookingStatus, Row
from storage.services import (
    ENTRY,
    EXIT,
    Slot,
    find_blockers,
    move_plans,
    occupancy_timeline,
)

WINDOW_COUNT = 13  # about 6 months of 2-week windows

# Colour thresholds (percentage of the row length used at the peak).
WARN_FROM = Decimal("70")
DANGER_ABOVE = Decimal("95")


def monday_of(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def windows(
    start: datetime.date, count: int, days: int
) -> list[tuple[datetime.date, datetime.date]]:
    """`count` consecutive windows of `days` days from `start`, as (first day, last day)."""
    return [
        (
            start + datetime.timedelta(days=i * days),
            start + datetime.timedelta(days=(i + 1) * days - 1),
        )
        for i in range(count)
    ]


def occupancy_level(used: Decimal, length: Decimal) -> str:
    """ "ok" (green) below 70 %, "warn" (orange) from 70 % to 95 %, "danger" (red) above 95 %."""
    percent = used * 100 / length if length else Decimal("100")
    if percent > DANGER_ABOVE:
        return "danger"
    if percent >= WARN_FROM:
        return "warn"
    return "ok"


@dataclass
class Cell:
    start: datetime.date
    end: datetime.date
    peak_m: Decimal
    length_m: Decimal
    has_blocking: bool
    vehicle_count: int

    @property
    def free_m(self) -> Decimal:
        return self.length_m - self.peak_m

    @property
    def level(self) -> str:
        return occupancy_level(self.peak_m, self.length_m)


@dataclass
class PlanningRow:
    row: Row
    length_m: Decimal
    cells: list[Cell] = field(default_factory=list)


@dataclass
class PlanningGrid:
    start: datetime.date
    windows: list[tuple[datetime.date, datetime.date]]
    rows: list[PlanningRow]
    min_free_m: Decimal | None = None


def _blocked_event_days(slots: list[Slot]) -> set[datetime.date]:
    """Days on which a vehicle of the row is boxed in when entering or leaving.

    A vehicle already in stock has no entry left to plan, as in `move_plans`.
    """
    days = set()
    for slot in slots:
        others = [other for other in slots if other is not slot]
        if slot.booking.status == BookingStatus.RESERVED and find_blockers(slot, others, ENTRY):
            days.add(slot.start)
        if find_blockers(slot, others, EXIT):
            days.add(slot.end)
    return days


def build_grid(
    start: datetime.date,
    count: int = WINDOW_COUNT,
    min_free_m: Decimal | None = None,
) -> PlanningGrid:
    """The planning grid from `start` (normally a Monday) for `count` windows.

    With `min_free_m`, only rows where at least one window has that much free space are kept.
    """
    app_settings = AppSettings.load()
    gap = app_settings.vehicle_gap_m
    grid_windows = windows(start, count, app_settings.period_days)
    first_day, last_day = grid_windows[0][0], grid_windows[-1][1]

    slots_by_row = defaultdict(list)
    bookings = (
        Booking.objects.active()
        .filter(row__is_active=True)
        .overlapping(first_day, last_day)
        .select_related("vehicle")
    )
    for booking in bookings:
        slots_by_row[booking.row_id].append(Slot.of(booking))

    planning_rows = []
    for row in Row.objects.filter(is_active=True):
        length = row.effective_length_for(app_settings)
        slots = slots_by_row[row.pk]
        blocked_days = _blocked_event_days(slots)
        planning_row = PlanningRow(row=row, length_m=length)
        for window_start, window_end in grid_windows:
            present = [slot for slot in slots if slot.overlaps(window_start, window_end)]
            peak = max(
                (used for _, _, used in occupancy_timeline(present, window_start, window_end, gap)),
                default=Decimal("0"),
            )
            planning_row.cells.append(
                Cell(
                    start=window_start,
                    end=window_end,
                    peak_m=peak,
                    length_m=length,
                    has_blocking=any(window_start <= day <= window_end for day in blocked_days),
                    vehicle_count=len(present),
                )
            )
        if min_free_m is None or any(cell.free_m >= min_free_m for cell in planning_row.cells):
            planning_rows.append(planning_row)
    return PlanningGrid(
        start=start, windows=grid_windows, rows=planning_rows, min_free_m=min_free_m
    )


@dataclass
class CellVehicle:
    booking: Booking
    plans: list  # MovePlan objects for this booking


def cell_details(row: Row, start: datetime.date, end: datetime.date) -> list[CellVehicle]:
    """Vehicles present in `row` during [start, end], by position, with their move plans."""
    bookings = (
        Booking.objects.active()
        .filter(row=row)
        .overlapping(start, end)
        .select_related("vehicle__client", "row")
        .order_by("position", "start_date")
    )
    return [CellVehicle(booking=booking, plans=move_plans(booking)) for booking in bookings]
