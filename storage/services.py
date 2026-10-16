"""Business rules for rows and bookings (CLAUDE.md, section 6).

- check_fit:          does a vehicle fit in a row, at a position, for some dates? (6.1)
- get_blockers:       which vehicles must be moved for a booking to leave or enter? (6.2)
- suggest_placements: best rows and positions for a new booking (6.3)
- settings checks:    bookings that would no longer fit after a settings change (6.5)

The rules work on "slots" (dates, length, position) so the same code checks real bookings
and hypothetical ones (a booking being created or moved, a row being shortened).
"""

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from clients.models import Vehicle
from core.formatting import format_money
from core.models import AppSettings
from core.pricing import Totals, band_count, compute_totals
from storage.models import Booking, BookingStatus, Row, compute_end_date

ROW_CODE_PATTERN = re.compile(r"^R(\d+)$")
MAX_ROWS_PER_BULK_CREATE = 200

ONE_DAY = datetime.timedelta(days=1)


# --- Rows --------------------------------------------------------------------


def create_rows(count: int) -> list[Row]:
    """Create `count` new rows, numbered after the highest existing "Rnn" code.

    With no rows yet, `create_rows(3)` creates R01, R02, R03. With R01..R10 existing it
    creates R11, R12, R13. Codes use at least 2 digits (R01 ... R99, then R100).
    The display order follows the number, so new rows appear at the end of the planning.
    """
    if not 1 <= count <= MAX_ROWS_PER_BULK_CREATE:
        raise ValueError(f"count must be between 1 and {MAX_ROWS_PER_BULK_CREATE}")

    with transaction.atomic():
        numbers = [
            int(match.group(1))
            for code in Row.objects.values_list("code", flat=True)
            if (match := ROW_CODE_PATTERN.match(code))
        ]
        last_number = max(numbers, default=0)
        last_order = max(Row.objects.values_list("display_order", flat=True), default=0)
        rows = [
            Row(code=f"R{number:02d}", display_order=last_order + index)
            for index, number in enumerate(range(last_number + 1, last_number + count + 1), 1)
        ]
        return Row.objects.bulk_create(rows)


# --- Slots: what the rules need to know about a booking ------------------------


@dataclass(frozen=True)
class Slot:
    """A vehicle occupying a row between two dates (both inclusive) at a position."""

    start: datetime.date
    end: datetime.date
    length: Decimal
    position: int
    booking: Booking | None = None  # None for a hypothetical booking

    @classmethod
    def of(cls, booking: Booking) -> "Slot":
        return cls(
            booking.start_date,
            booking.end_date,
            booking.vehicle.length_m,
            booking.position,
            booking,
        )

    def overlaps(self, start: datetime.date, end: datetime.date) -> bool:
        return self.start <= end and self.end >= start


def occupancy(lengths: list[Decimal], gap: Decimal) -> Decimal:
    """Metres used by vehicles parked one after another: lengths + a gap between each two."""
    if not lengths:
        return Decimal("0")
    return sum(lengths, Decimal("0")) + gap * (len(lengths) - 1)


def occupancy_timeline(slots: list[Slot], start: datetime.date, end: datetime.date, gap: Decimal):
    """Yield (day, slots present, metres used) for each day in [start, end] where the set of
    vehicles changes. Occupancy is constant between two change days, so checking these days
    is the same as checking every day (a "sweep" over the change dates)."""
    change_days = {start}
    for slot in slots:
        if start < slot.start <= end:
            change_days.add(slot.start)
        if start <= slot.end + ONE_DAY <= end:
            change_days.add(slot.end + ONE_DAY)
    for day in sorted(change_days):
        present = [slot for slot in slots if slot.start <= day <= slot.end]
        yield day, present, occupancy([slot.length for slot in present], gap)


# --- 6.1 Fit check -------------------------------------------------------------


@dataclass
class FitResult:
    ok: bool
    peak_occupancy_m: Decimal
    free_m_at_peak: Decimal
    row_length_m: Decimal
    # Bookings present on the most crowded day, when the row is too full.
    length_conflicts: list[Booking] = field(default_factory=list)
    # Overlapping bookings already using the same position in the row.
    position_conflicts: list[Booking] = field(default_factory=list)
    # Other active bookings of the same vehicle at the same time.
    vehicle_conflicts: list[Booking] = field(default_factory=list)

    @property
    def conflicts(self) -> list[Booking]:
        return self.length_conflicts + self.position_conflicts + self.vehicle_conflicts


def _fit(candidate: Slot, others: list[Slot], row_length: Decimal, gap: Decimal) -> FitResult:
    """Pure fit check of `candidate` against the other active slots of the same row."""
    others = [slot for slot in others if slot.overlaps(candidate.start, candidate.end)]
    peak, peak_present = Decimal("0"), []
    slots = others + [candidate]
    for _, present, used in occupancy_timeline(slots, candidate.start, candidate.end, gap):
        if used > peak:
            peak, peak_present = used, present
    too_long = peak > row_length
    position_conflicts = [s.booking for s in others if s.position == candidate.position]
    return FitResult(
        ok=not too_long and not position_conflicts,
        peak_occupancy_m=peak,
        free_m_at_peak=row_length - peak,
        row_length_m=row_length,
        length_conflicts=[s.booking for s in peak_present if s is not candidate]
        if too_long
        else [],
        position_conflicts=position_conflicts,
    )


def _active_slots(row: Row, start, end, exclude_booking: Booking | None = None) -> list[Slot]:
    bookings = (
        Booking.objects.active()
        .filter(row=row)
        .overlapping(start, end)
        .select_related("vehicle", "row")
    )
    if exclude_booking is not None and exclude_booking.pk:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    return [Slot.of(booking) for booking in bookings]


def vehicle_conflicts(vehicle: Vehicle, start, end, exclude_booking=None) -> list[Booking]:
    """Other active bookings of the same vehicle overlapping [start, end]."""
    bookings = Booking.objects.active().filter(vehicle=vehicle).overlapping(start, end)
    if exclude_booking is not None and exclude_booking.pk:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    return list(bookings.select_related("row", "vehicle"))


def check_fit(
    row: Row,
    vehicle: Vehicle,
    start: datetime.date,
    end: datetime.date,
    position: int,
    exclude_booking: Booking | None = None,
) -> FitResult:
    """Can `vehicle` be stored in `row` at `position` on every day of [start, end]?

    On each day, the active bookings present plus this one must satisfy
    sum(lengths) + gap × (number of vehicles − 1) ≤ row length, and no overlapping
    booking may use the same position. A vehicle cannot be booked twice at the same time.
    `exclude_booking` is the booking being edited, so it is not compared with itself.
    """
    app_settings = AppSettings.load()
    candidate = Slot(start, end, vehicle.length_m, position)
    result = _fit(
        candidate,
        _active_slots(row, start, end, exclude_booking),
        row.effective_length_for(app_settings),
        app_settings.vehicle_gap_m,
    )
    result.vehicle_conflicts = vehicle_conflicts(vehicle, start, end, exclude_booking)
    result.ok = result.ok and not result.vehicle_conflicts
    return result


# --- 6.2 Boxed-in detection ----------------------------------------------------

EXIT, ENTRY = "exit", "entry"


def find_blockers(candidate: Slot, others: list[Slot], event: str) -> list[Slot]:
    """Slots closer to the aisle that are physically present when `candidate` leaves/enters."""
    if event == EXIT:
        found = [
            slot
            for slot in others
            if slot.position < candidate.position
            and slot.start <= candidate.end
            and slot.end > candidate.end
        ]
    elif event == ENTRY:
        found = [
            slot
            for slot in others
            if slot.position < candidate.position
            and slot.start < candidate.start
            and slot.end >= candidate.start
        ]
    else:
        raise ValueError(f"event must be {EXIT!r} or {ENTRY!r}")
    return sorted(found, key=lambda slot: slot.position)


def _blocked_by_candidate(candidate: Slot, others: list[Slot]) -> list[Slot]:
    """Other slots whose exit or entry would be blocked by `candidate`."""
    return [
        slot
        for slot in others
        if find_blockers(slot, [candidate], EXIT) or find_blockers(slot, [candidate], ENTRY)
    ]


def get_blockers(booking: Booking, event: str = EXIT) -> list[Booking]:
    """Bookings that must be moved out of the way for `booking` to leave (exit, on its end
    date) or come in (entry, on its start date).

    Sorted by position, closest to the aisle first: the order in which to take them out.
    They are put back in reverse order. Only active bookings count.
    """
    others = _active_slots(booking.row, booking.start_date, booking.end_date, booking)
    return [slot.booking for slot in find_blockers(Slot.of(booking), others, event)]


@dataclass
class MovePlan:
    """What to move, in which order, for a vehicle to leave or enter its row."""

    booking: Booking
    event: str
    blockers: list[Booking]

    @property
    def date(self) -> datetime.date:
        return self.booking.end_date if self.event == EXIT else self.booking.start_date

    @property
    def verb(self) -> str:
        return "sortir" if self.event == EXIT else "rentrer"

    def as_text(self) -> str:
        """Plain-text version, used in emails. Templates render the same sentence in HTML."""
        moves = ", puis ".join(f"{b.vehicle.plate} (pos. {b.position})" for b in self.blockers)
        put_back = (
            "Les replacer ensuite dans l'ordre inverse."
            if len(self.blockers) > 1
            else "Le replacer ensuite."
        )
        return (
            f"Pour {self.verb} {self.booking.vehicle.plate} (position {self.booking.position}) "
            f"le {self.date:%d/%m/%Y} : déplacer d'abord {moves}. {put_back}"
        )


def move_plans(booking: Booking) -> list[MovePlan]:
    """Move plans for an active booking (empty if not blocked): its entry while it is still
    "réservée", and its exit. A vehicle already in stock has no entry left to plan."""
    if not booking.is_active:
        return []
    events = [EXIT] if booking.status == BookingStatus.STORED else [ENTRY, EXIT]
    plans = [MovePlan(booking, event, get_blockers(booking, event)) for event in events]
    return [plan for plan in plans if plan.blockers]


def placement_warnings(
    row: Row,
    vehicle: Vehicle,
    start: datetime.date,
    end: datetime.date,
    position: int,
    exclude_booking: Booking | None = None,
) -> list[str]:
    """Blocking situations a booking would create, as French sentences for the booking form:
    vehicles in its way when it enters or leaves (with the move plan), and vehicles it would
    be in the way of."""
    others = _active_slots(row, start, end, exclude_booking)
    candidate = Slot(start, end, vehicle.length_m, position)
    planned = Booking(vehicle=vehicle, row=row, position=position, start_date=start, end_date=end)
    warnings = []
    for event in (ENTRY, EXIT):
        blockers = [slot.booking for slot in find_blockers(candidate, others, event)]
        if blockers:
            warnings.append(MovePlan(planned, event, blockers).as_text())
    for slot in _blocked_by_candidate(candidate, others):
        blocked = slot.booking
        if find_blockers(slot, [candidate], EXIT):
            warnings.append(
                f"Ce véhicule bloquera la sortie de {blocked.vehicle.plate} "
                f"(pos. {blocked.position}) le {blocked.end_date:%d/%m/%Y}."
            )
        if find_blockers(slot, [candidate], ENTRY):
            warnings.append(
                f"Ce véhicule bloquera l'entrée de {blocked.vehicle.plate} "
                f"(pos. {blocked.position}) le {blocked.start_date:%d/%m/%Y}."
            )
    return warnings


# --- 6.3 Placement suggestions -------------------------------------------------


@dataclass
class Suggestion:
    row: Row
    position: int
    fit: FitResult
    blocked_by: list[Booking]  # vehicles in the way when this one enters or leaves
    blocks: list[Booking]  # vehicles this one would be in the way of

    @property
    def conflict_count(self) -> int:
        return len({b.pk for b in self.blocked_by} | {b.pk for b in self.blocks})

    @property
    def wasted_m(self) -> Decimal:
        return self.fit.free_m_at_peak


def suggest_placements(
    vehicle: Vehicle,
    start: datetime.date,
    end: datetime.date,
    exclude_booking: Booking | None = None,
) -> list[Suggestion]:
    """Every active row and position where the vehicle fits for [start, end], best first.

    Ranking: 1. fewest blocking conflicts (both directions, entry and exit),
    2. least free space left at the peak (keeps big gaps for big vehicles),
    3. row display order. This naturally puts vehicles leaving later deeper in the row.
    """
    if vehicle_conflicts(vehicle, start, end, exclude_booking):
        return []

    app_settings = AppSettings.load()
    gap = app_settings.vehicle_gap_m
    bookings = (
        Booking.objects.active()
        .filter(row__is_active=True)
        .overlapping(start, end)
        .select_related("vehicle", "row")
    )
    if exclude_booking is not None and exclude_booking.pk:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    slots_by_row = defaultdict(list)
    for booking in bookings:
        slots_by_row[booking.row_id].append(Slot.of(booking))

    suggestions = []
    for row in Row.objects.filter(is_active=True):
        others = slots_by_row[row.pk]
        row_length = row.effective_length_for(app_settings)
        # Positions beyond the deepest one in use are all equivalent: try one of them.
        deepest = max((slot.position for slot in others), default=0)
        for position in range(1, deepest + 2):
            candidate = Slot(start, end, vehicle.length_m, position)
            fit = _fit(candidate, others, row_length, gap)
            if not fit.ok:
                continue
            blocked_by = find_blockers(candidate, others, EXIT)
            blocked_by += find_blockers(candidate, others, ENTRY)
            blocks = _blocked_by_candidate(candidate, others)
            suggestions.append(
                Suggestion(
                    row=row,
                    position=position,
                    fit=fit,
                    blocked_by=list({s.booking.pk: s.booking for s in blocked_by}.values()),
                    blocks=[slot.booking for slot in blocks],
                )
            )
    suggestions.sort(
        key=lambda s: (s.conflict_count, s.wasted_m, s.row.display_order, s.row.code, s.position)
    )
    return suggestions


# --- Price per band (vehicle length) --------------------------------------------


def is_invoiced(booking: Booking) -> bool:
    """True once some periods are on an invoice that is not cancelled (a draft counts)."""
    from invoicing.services import invoiced_periods  # invoicing depends on storage

    return invoiced_periods(booking) > 0


@dataclass
class PriceChange:
    """The vehicle length gives another number of bands than the booking's price."""

    booking: Booking
    old_bands: int
    new_bands: int
    applied: bool  # False: the booking is already invoiced, its price is kept

    def as_text(self) -> str:
        b = self.booking
        stay = f"réservation du {b.start_date:%d/%m/%Y} au {b.end_date:%d/%m/%Y}"
        if self.applied:
            return (
                f"Prix recalculé pour la {stay} : {self.new_bands} tranche(s) au lieu de "
                f"{self.old_bands}, soit {format_money(b.price_per_period)} HTVA par période."
            )
        return (
            f"La {stay} est déjà facturée : son prix reste basé sur {self.old_bands} "
            f"tranche(s) au lieu de {self.new_bands}. Pour le corriger : supprimez le brouillon "
            "de facture et recréez-le, ou, si la facture est émise, faites une note de crédit "
            "puis une nouvelle facture."
        )


def refresh_price(booking: Booking) -> PriceChange | None:
    """Recalculate the bands from the vehicle's current length.

    Applied only while the booking is not invoiced: once on an invoice, its price stays as
    invoiced (corrections go through a credit note and a new invoice). Returns None when the
    number of bands does not change, or for a booking with a flat price (before bands).
    """
    if not booking.priced_per_band:
        return None
    old_bands = booking.band_count
    new_bands = band_count(booking.vehicle.length_m, booking.band_length_m)
    if booking.billed_length_m == booking.vehicle.length_m:
        return None
    if is_invoiced(booking):
        if new_bands == old_bands:
            return None
        return PriceChange(booking, old_bands, new_bands, applied=False)
    booking.compute_price()
    booking.save(update_fields=["billed_length_m", "band_count", "price_per_period", "updated_at"])
    if new_bands == old_bands:
        return None  # same price, only the recorded length was updated
    return PriceChange(booking, old_bands, new_bands, applied=True)


def refresh_vehicle_prices(vehicle: Vehicle) -> list[PriceChange]:
    """After the vehicle length was corrected: `refresh_price` on each of its bookings."""
    bookings = vehicle.bookings.exclude(status=BookingStatus.CANCELLED).select_related("vehicle")
    return [change for booking in bookings if (change := refresh_price(booking))]


@dataclass(frozen=True)
class PricePreview:
    """Price shown live in the booking form."""

    length_m: Decimal | None
    band_length_m: Decimal | None
    band_count: int | None
    price_per_band: Decimal | None
    price_per_period: Decimal
    totals: Totals


def price_preview(
    vehicle: Vehicle | None, periods: int, booking: Booking | None = None
) -> PricePreview | None:
    """Price of `periods` periods for `vehicle`, shown live in the booking form.

    A new booking uses today's settings. An existing one uses its own band size and price per
    band; once invoiced (or with a flat price from before bands) its price is shown as is.
    Returns None while the vehicle, the periods or the price per band is missing.
    """
    if not periods:
        return None
    editing = booking is not None and booking.pk is not None
    if editing and (not booking.priced_per_band or is_invoiced(booking)):
        price = booking.price_per_period
        return PricePreview(
            length_m=booking.billed_length_m,
            band_length_m=booking.band_length_m,
            band_count=booking.band_count,
            price_per_band=booking.price_per_band,
            price_per_period=price,
            totals=compute_totals(periods, price, booking.vat_regime, booking.vat_rate),
        )
    source = booking if editing else AppSettings.load()
    if vehicle is None or source.price_per_band is None:
        return None
    bands = band_count(vehicle.length_m, source.band_length_m)
    price = bands * source.price_per_band
    return PricePreview(
        length_m=vehicle.length_m,
        band_length_m=source.band_length_m,
        band_count=bands,
        price_per_band=source.price_per_band,
        price_per_period=price,
        totals=compute_totals(periods, price, source.vat_regime, source.vat_rate),
    )


# --- Status changes ------------------------------------------------------------


class BookingActionError(Exception):
    """An action that is not allowed in the booking's current state. Message in French."""


def today() -> datetime.date:
    return timezone.localdate()


def mark_stored(booking: Booking, check_in: datetime.date) -> None:
    if booking.status != BookingStatus.RESERVED:
        raise BookingActionError("Seule une réservation « réservée » peut être mise en stock.")
    booking.status = BookingStatus.STORED
    booking.actual_check_in = check_in
    booking.save()


def mark_ended(booking: Booking, check_out: datetime.date) -> None:
    if booking.status != BookingStatus.STORED:
        raise BookingActionError("Seul un véhicule « en stock » peut être marqué sorti.")
    if booking.actual_check_in and check_out < booking.actual_check_in:
        raise BookingActionError("La date de sortie est antérieure à la date d'entrée.")
    booking.status = BookingStatus.ENDED
    booking.actual_check_out = check_out
    booking.save()


def cancel(booking: Booking) -> None:
    if booking.status != BookingStatus.RESERVED:
        raise BookingActionError(
            "Seule une réservation pas encore entrée peut être annulée. "
            "Pour un véhicule en stock, utilisez « Marquer sortie »."
        )
    booking.status = BookingStatus.CANCELLED
    booking.save()


@dataclass
class ExtensionCheck:
    new_end_date: datetime.date
    fit: FitResult
    new_exit_blockers: list[Booking]
    newly_blocked: list[Booking]
    applied: bool = False

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.new_exit_blockers or self.newly_blocked)


def check_extension(booking: Booking, added_periods: int) -> ExtensionCheck:
    """Fit and boxed-in checks for "Prolonger" before applying it."""
    if not booking.is_active:
        raise BookingActionError("Seule une réservation en cours peut être prolongée.")
    period_days = AppSettings.load().period_days
    new_end = compute_end_date(booking.start_date, booking.periods + added_periods, period_days)
    fit = check_fit(
        booking.row, booking.vehicle, booking.start_date, new_end, booking.position, booking
    )
    others = _active_slots(booking.row, booking.start_date, new_end, booking)
    extended = Slot(
        booking.start_date, new_end, booking.vehicle.length_m, booking.position, booking
    )
    current = Slot.of(booking)
    newly_blocked = [
        slot.booking
        for slot in _blocked_by_candidate(extended, others)
        if slot not in _blocked_by_candidate(current, others)
    ]
    return ExtensionCheck(
        new_end_date=new_end,
        fit=fit,
        new_exit_blockers=[s.booking for s in find_blockers(extended, others, EXIT)],
        newly_blocked=newly_blocked,
    )


def extend(booking: Booking, added_periods: int, confirmed: bool = False) -> ExtensionCheck:
    """Add periods to a booking. Refused if it no longer fits; needs `confirmed` if the
    longer stay creates blocking situations. The price per period stays the one recorded at
    creation. (The complementary invoice for the added periods arrives with invoicing, M5.)"""
    check = check_extension(booking, added_periods)
    if not check.fit.ok:
        raise BookingActionError(
            "Prolongation impossible : le véhicule ne tient plus dans la rangée."
        )
    if check.needs_confirmation and not confirmed:
        return check
    booking.periods += added_periods
    booking.save()
    check.applied = True
    return check


# --- 6.5 Settings changes that affect existing bookings ------------------------


def current_and_future_bookings():
    return Booking.objects.active().filter(end_date__gte=today()).select_related("vehicle", "row")


def bookings_not_fitting(
    default_row_length: Decimal | None = None,
    gap: Decimal | None = None,
    row_lengths: dict[int, Decimal | None] | None = None,
) -> list[Booking]:
    """Current and future active bookings that would no longer fit with new values.

    `default_row_length` and `gap` replace the settings values; `row_lengths` maps a row id
    to a new length override (None = use the default). Nothing is saved or changed.
    """
    app_settings = AppSettings.load()
    if default_row_length is None:
        default_row_length = app_settings.default_row_length_m
    gap = app_settings.vehicle_gap_m if gap is None else gap
    row_lengths = row_lengths or {}

    slots_by_row = defaultdict(list)
    for booking in current_and_future_bookings():
        slots_by_row[booking.row].append(Slot.of(booking))

    affected = []
    for row, slots in slots_by_row.items():
        override = row_lengths.get(row.pk, row.length_override_m)
        length = override if override is not None else default_row_length
        start = max(today(), min(slot.start for slot in slots))
        end = max(slot.end for slot in slots)
        for _, present, used in occupancy_timeline(slots, start, end, gap):
            if used > length:
                affected.extend(slot.booking for slot in present if slot.booking not in affected)
    return sorted(affected, key=lambda b: (b.row.display_order, b.start_date, b.position))


def bookings_preventing_deactivation(row: Row) -> list[Booking]:
    """Current and future active bookings in a row (a row with any cannot be deactivated)."""
    return list(current_and_future_bookings().filter(row=row))
