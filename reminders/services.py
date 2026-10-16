"""End-of-storage reminders (CLAUDE.md, section 9), sent by `manage.py send_reminders`.

Run once a day. Safe to run twice: a reminder is sent only if no successful ReminderLog
exists for it. If the job did not run for a few days, the next run catches up with every
booking now inside the reminder window.
"""

import datetime
import logging
import smtplib
from dataclasses import dataclass, field

from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import AppSettings
from reminders.models import ReminderKind, ReminderLog
from storage.models import Booking, BookingStatus
from storage.services import ENTRY, EXIT, MovePlan, get_blockers

logger = logging.getLogger(__name__)

# The admin digest looks at entries in the next 14 days (CLAUDE.md, section 9.1).
DIGEST_DAYS = 14


@dataclass
class Outcome:
    kind: str
    recipients: list[str]
    subject: str
    booking: Booking | None = None
    success: bool = True
    error: str = ""


@dataclass
class Report:
    dry_run: bool
    today: datetime.date
    outcomes: list[Outcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def sent(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.success)

    @property
    def failed(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.success)


# --- Who gets a reminder ---------------------------------------------------------


def bookings_ending_soon(today: datetime.date, days: int):
    """Active bookings whose last day is between today and today + `days` (both included)."""
    return (
        Booking.objects.active()
        .filter(end_date__gte=today, end_date__lte=today + datetime.timedelta(days=days))
        .select_related("vehicle__client", "row")
        .order_by("end_date", "row__display_order", "position")
    )


def already_sent(booking: Booking, kind: str) -> bool:
    return ReminderLog.objects.filter(booking=booking, kind=kind, success=True).exists()


def blocked_entries(today: datetime.date) -> list[MovePlan]:
    """Move plans for reservations starting in the next 14 days whose entry is blocked."""
    upcoming = (
        Booking.objects.filter(
            status=BookingStatus.RESERVED,
            start_date__gte=today,
            start_date__lte=today + datetime.timedelta(days=DIGEST_DAYS),
        )
        .select_related("vehicle__client", "row")
        .order_by("start_date", "row__display_order", "position")
    )
    plans = [MovePlan(booking, ENTRY, get_blockers(booking, ENTRY)) for booking in upcoming]
    return [plan for plan in plans if plan.blockers]


# --- Email contents --------------------------------------------------------------


def client_placeholders(booking: Booking, app_settings: AppSettings) -> dict[str, str]:
    """Values for the placeholders of the editable client reminder (section 9.2)."""
    return {
        "client_nom": booking.vehicle.client.display_name,
        "plaque": booking.vehicle.plate,
        "date_fin": f"{booking.end_date:%d/%m/%Y}",
        "rangee": booking.row.code,
        "societe_nom": app_settings.company_name,
        "societe_telephone": app_settings.company_phone,
        "societe_email": app_settings.company_email,
    }


def text_to_html(text: str) -> str:
    """Simple HTML version of a plain-text email: escaped, paragraphs kept."""
    return render_to_string("reminders/email_base.html", {"body": text})


def client_email(booking: Booking, app_settings: AppSettings) -> tuple[str, str]:
    values = client_placeholders(booking, app_settings)
    subject = app_settings.client_reminder_subject.format_map(values)
    body = app_settings.client_reminder_body.format_map(values)
    return " ".join(subject.split()), body


def admin_email(booking: Booking, client_reminded: bool, today: datetime.date) -> tuple[str, str]:
    exit_plan = MovePlan(booking, EXIT, get_blockers(booking, EXIT))
    context = {
        "booking": booking,
        "client": booking.vehicle.client,
        "client_reminded": client_reminded,
        "days_left": (booking.end_date - today).days,
        "exit_plan": exit_plan if exit_plan.blockers else None,
    }
    subject = f"[Stockage] Fin de stockage : {booking.vehicle.plate} le {booking.end_date:%d/%m/%Y}"
    if exit_plan.blockers:
        subject += " – sortie bloquée"
    return subject, render_to_string("reminders/admin_end_notice.txt", context)


def digest_email(plans: list[MovePlan], today: datetime.date) -> tuple[str, str]:
    subject = f"[Stockage] {len(plans)} entrée(s) bloquée(s) dans les {DIGEST_DAYS} prochains jours"
    body = render_to_string(
        "reminders/entry_digest.txt", {"plans": plans, "today": today, "days": DIGEST_DAYS}
    )
    return subject, body


# --- Sending ---------------------------------------------------------------------


def _send(subject: str, body: str, recipients: list[str], app_settings: AppSettings) -> None:
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=app_settings.sender_email,
        to=recipients,
        reply_to=[app_settings.company_email] if app_settings.company_email else None,
    )
    message.attach_alternative(text_to_html(body), "text/html")
    message.send()


def _deliver(report: Report, outcome: Outcome, body: str, app_settings, digest_date=None):
    """Send one email (unless dry run) and record the attempt in ReminderLog."""
    report.outcomes.append(outcome)
    if report.dry_run:
        return
    try:
        _send(outcome.subject, body, outcome.recipients, app_settings)
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Reminder %s failed", outcome.kind)
        outcome.success, outcome.error = False, str(exc) or exc.__class__.__name__
    try:
        with transaction.atomic():
            ReminderLog.objects.create(
                booking=outcome.booking,
                kind=outcome.kind,
                digest_date=digest_date,
                recipients=", ".join(outcome.recipients),
                success=outcome.success,
                error_message=outcome.error,
            )
    except IntegrityError:
        # Another run sent the same reminder at the same moment: keep the first log.
        logger.warning("Reminder %s already logged for %s", outcome.kind, outcome.booking)


def send_reminders(today: datetime.date | None = None, dry_run: bool = False) -> Report:
    """Send the due reminders. With `dry_run`, only report what would be sent."""
    today = today or timezone.localdate()
    app_settings = AppSettings.load()
    report = Report(dry_run=dry_run, today=today)
    admins = app_settings.admin_emails
    if not admins:
        report.warnings.append(
            "Aucun email d'administrateur dans les Paramètres : rappels internes non envoyés."
        )

    for booking in bookings_ending_soon(today, app_settings.reminder_days_before_end):
        client_reminded = already_sent(booking, ReminderKind.CLIENT_END_NOTICE)
        if not client_reminded:
            subject, body = client_email(booking, app_settings)
            outcome = Outcome(
                ReminderKind.CLIENT_END_NOTICE, [booking.vehicle.client.email], subject, booking
            )
            _deliver(report, outcome, body, app_settings)
            client_reminded = outcome.success and not dry_run
        if admins and not already_sent(booking, ReminderKind.ADMIN_END_NOTICE):
            subject, body = admin_email(booking, client_reminded, today)
            outcome = Outcome(ReminderKind.ADMIN_END_NOTICE, admins, subject, booking)
            _deliver(report, outcome, body, app_settings)

    digest_done = ReminderLog.objects.filter(
        kind=ReminderKind.ENTRY_DIGEST, digest_date=today, success=True
    ).exists()
    if admins and not digest_done:
        plans = blocked_entries(today)
        if plans:  # nothing to report: no email
            subject, body = digest_email(plans, today)
            outcome = Outcome(ReminderKind.ENTRY_DIGEST, admins, subject)
            _deliver(report, outcome, body, app_settings, digest_date=today)
    return report
