"""Figures for the "Tableau de bord" (CLAUDE.md, section 7.1)."""

import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from core.charts import Bar, bar_chart
from core.formatting import format_metres, format_money
from core.models import AppSettings
from invoicing.models import CreditNote, CreditNoteStatus, Invoice, InvoiceStatus
from invoicing.services import remaining_to_credit
from reminders.models import ReminderKind, ReminderLog
from storage import planning
from storage.models import Booking, BookingStatus, Row
from storage.services import ENTRY, EXIT, get_blockers, occupancy

UPCOMING_DAYS = 14  # "dans les 14 prochains jours"
FORECAST_WINDOWS = 12
REVENUE_MONTHS = 12
MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
             "juil.", "août", "sept.", "oct.", "nov.", "déc."]  # fmt: skip


@dataclass
class Occupancy:
    used_m: Decimal
    total_m: Decimal
    vehicles: int

    @property
    def free_m(self) -> Decimal:
        return self.total_m - self.used_m

    @property
    def percent(self) -> Decimal:
        return self.used_m * 100 / self.total_m if self.total_m else Decimal(0)


def occupancy_on(day: datetime.date) -> Occupancy:
    """Metres used (vehicles + gaps) in all active rows on one day."""
    app_settings = AppSettings.load()
    rows = list(Row.objects.filter(is_active=True))
    lengths = defaultdict(list)
    present = (
        Booking.objects.active()
        .filter(row__is_active=True, start_date__lte=day, end_date__gte=day)
        .select_related("vehicle")
    )
    for booking in present:
        lengths[booking.row_id].append(booking.vehicle.length_m)
    used = sum((occupancy(lengths[row.pk], app_settings.vehicle_gap_m) for row in rows), Decimal(0))
    total = sum((row.effective_length_for(app_settings) for row in rows), Decimal(0))
    return Occupancy(used_m=used, total_m=total, vehicles=sum(len(v) for v in lengths.values()))


@dataclass
class InvoiceFigures:
    unpaid_count: int
    unpaid_amount: Decimal
    overdue_count: int
    overdue_amount: Decimal


def invoice_figures(today: datetime.date) -> InvoiceFigures:
    """Issued, unpaid invoices (amounts net of partial credit notes) and the overdue ones."""
    unpaid = list(Invoice.objects.filter(status=InvoiceStatus.ISSUED))
    overdue = [invoice for invoice in unpaid if invoice.due_date and invoice.due_date < today]
    return InvoiceFigures(
        unpaid_count=len(unpaid),
        unpaid_amount=sum((remaining_to_credit(i) for i in unpaid), Decimal(0)),
        overdue_count=len(overdue),
        overdue_amount=sum((remaining_to_credit(i) for i in overdue), Decimal(0)),
    )


@dataclass
class UpcomingEvent:
    booking: Booking
    blockers: list[Booking]
    reminder_sent: bool = False


def ending_soon(today: datetime.date) -> list[UpcomingEvent]:
    """Active bookings ending in the next 14 days, with reminder and blocked-exit status."""
    bookings = (
        Booking.objects.active()
        .filter(end_date__gte=today, end_date__lte=today + datetime.timedelta(days=UPCOMING_DAYS))
        .select_related("vehicle__client", "row")
        .order_by("end_date", "row__display_order", "position")
    )
    reminded = set(
        ReminderLog.objects.filter(
            kind=ReminderKind.CLIENT_END_NOTICE, success=True, booking__in=bookings
        ).values_list("booking_id", flat=True)
    )
    return [
        UpcomingEvent(booking, get_blockers(booking, EXIT), booking.pk in reminded)
        for booking in bookings
    ]


def upcoming_entries(today: datetime.date) -> list[UpcomingEvent]:
    """Reservations starting in the next 14 days, with blocked-entry status."""
    bookings = (
        Booking.objects.filter(
            status=BookingStatus.RESERVED,
            start_date__gte=today,
            start_date__lte=today + datetime.timedelta(days=UPCOMING_DAYS),
        )
        .select_related("vehicle__client", "row")
        .order_by("start_date", "row__display_order", "position")
    )
    return [UpcomingEvent(booking, get_blockers(booking, ENTRY)) for booking in bookings]


def documents_to_complete(today: datetime.date) -> list[Booking]:
    """Bookings in stock or starting within UPCOMING_DAYS days whose ID or insurance is not
    checked as valid yet (both are checked for every booking)."""
    horizon = today + datetime.timedelta(days=UPCOMING_DAYS)
    return list(
        Booking.objects.active()
        .documents_incomplete()
        .filter(start_date__lte=horizon)
        .select_related("vehicle__client", "row")
        .order_by("start_date", "row__display_order", "position")
    )


def failed_reminders(today: datetime.date):
    """Failed reminders of the last 30 days that have not been sent successfully since."""
    failures = (
        ReminderLog.objects.filter(
            success=False, sent_at__date__gte=today - datetime.timedelta(days=30)
        )
        .select_related("booking__vehicle")
        .order_by("-sent_at")
    )
    failures = list(failures)
    succeeded = set(
        ReminderLog.objects.filter(
            success=True, booking_id__in={f.booking_id for f in failures if f.booking_id}
        ).values_list("booking_id", "kind")
    )
    # A failed digest is not retried once its day has passed, so only per-booking failures
    # can be "fixed" by a later successful send.
    return [f for f in failures if (f.booking_id, f.kind) not in succeeded]


def occupancy_forecast_chart(today: datetime.date):
    """Bar chart: occupancy % (sum of each row's peak) for the next 12 two-week windows."""
    grid = planning.build_grid(planning.monday_of(today), count=FORECAST_WINDOWS)
    total = sum((row.length_m for row in grid.rows), Decimal(0))
    bars = []
    for index, (start, end) in enumerate(grid.windows):
        peak = sum((row.cells[index].peak_m for row in grid.rows), Decimal(0))
        percent = peak * 100 / total if total else Decimal(0)
        bars.append(
            Bar(
                label=f"{start:%d/%m}",
                value=percent,
                tooltip=f"Du {start:%d/%m/%Y} au {end:%d/%m/%Y} : {percent:.0f} % "
                f"({format_metres(peak)} sur {format_metres(total)})",
                table_label=f"du {start:%d/%m/%Y} au {end:%d/%m/%Y}",
            )
        )
    return bar_chart(
        bars,
        maximum=Decimal(100),
        tick_format=lambda v: f"{v:.0f} %",
        reference_lines=[(Decimal(70), "70 %"), (Decimal(95), "95 %")],
    )


def _month_starts(today: datetime.date, count: int) -> list[datetime.date]:
    """First day of the last `count` months, oldest first, ending with the current month."""
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(datetime.date(year, month, 1))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return list(reversed(months))


def monthly_revenue(today: datetime.date) -> list[tuple[datetime.date, Decimal]]:
    """Total excl. VAT of issued invoices per month, minus the credit notes of that month."""
    months = _month_starts(today, REVENUE_MONTHS)
    totals = {month: Decimal(0) for month in months}
    since = months[0]

    invoiced = (
        Invoice.objects.exclude(status=InvoiceStatus.DRAFT)
        .filter(issue_date__gte=since, issue_date__lte=today)
        .values_list("issue_date", "total_excl_vat")
    )
    credited = CreditNote.objects.filter(
        status=CreditNoteStatus.ISSUED, issue_date__gte=since, issue_date__lte=today
    ).values_list("issue_date", "total_excl_vat")
    for day, amount in invoiced:
        totals[day.replace(day=1)] += amount
    for day, amount in credited:
        totals[day.replace(day=1)] -= amount
    return list(totals.items())


def _month_label(month: datetime.date) -> str:
    """ "mars", or "janv. 27" for January so the year change is visible on the axis."""
    label = MONTHS_FR[month.month - 1]
    return f"{label} {month:%y}" if month.month == 1 else label


def revenue_chart(today: datetime.date):
    data = monthly_revenue(today)
    bars = [
        Bar(
            label=_month_label(month),
            value=amount,
            tooltip=f"{MONTHS_FR[month.month - 1]} {month.year} : {format_money(amount)} HTVA",
            table_label=f"{MONTHS_FR[month.month - 1]} {month.year}",
        )
        for month, amount in data
    ]
    return bar_chart(bars, tick_format=_compact_euros)


def _compact_euros(value: Decimal) -> str:
    """Axis labels: 0 €, 500 €, 1 k€, 2,5 k€ (exact amounts are in the tooltip and table)."""
    if value >= 1000:
        return f"{value / 1000:g}".replace(".", ",") + "\u202fk€"
    return f"{value:.0f}\u202f€"


def active_booking_count() -> int:
    return Booking.objects.active().count()
