"""M6: end-of-storage reminders (CLAUDE.md, sections 9 and 11)."""

import datetime
import smtplib
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse

from reminders import services
from reminders.models import ReminderKind, ReminderLog
from storage.models import BookingStatus
from tests.factories import make_booking, make_client, make_row, make_vehicle, set_settings

pytestmark = pytest.mark.django_db

D = datetime.date
TODAY = D(2027, 3, 10)


@pytest.fixture(autouse=True)
def reminder_settings():
    set_settings(
        price_per_period=Decimal("45.00"),
        default_row_length_m=Decimal("30.00"),
        reminder_days_before_end=14,
        company_name="Stockage Ardennes",
        company_phone="063 12 34 56",
        company_email="contact@stockage.be",
        admin_notification_emails="marie@stockage.be, paul@stockage.be",
    )


def booking_ending(end, position=1, row=None, client=None, **fields):
    """Booking of 1 period (14 days) whose last day is `end`."""
    vehicle = make_vehicle(client=client or make_client(), **fields.pop("vehicle_fields", {}))
    start = end - datetime.timedelta(days=13)
    return make_booking(row or make_row(), position, start, periods=1, vehicle=vehicle, **fields)


def emails_to(mailoutbox, address):
    return [message for message in mailoutbox if address in message.to]


# --- Who gets a reminder ---------------------------------------------------------


def test_window_is_from_today_to_reminder_days(mailoutbox):
    ending_today = booking_ending(TODAY)
    ending_in_14 = booking_ending(TODAY + datetime.timedelta(days=14))
    booking_ending(TODAY + datetime.timedelta(days=15))  # too early
    booking_ending(TODAY - datetime.timedelta(days=1))  # already over
    services.send_reminders(today=TODAY)
    reminded = {
        log.booking for log in ReminderLog.objects.filter(kind=ReminderKind.CLIENT_END_NOTICE)
    }
    assert reminded == {ending_today, ending_in_14}


def test_only_active_bookings_get_reminders(mailoutbox):
    booking_ending(TODAY + datetime.timedelta(days=3), status=BookingStatus.CANCELLED)
    booking_ending(TODAY + datetime.timedelta(days=3), status=BookingStatus.ENDED)
    stored = booking_ending(TODAY + datetime.timedelta(days=3), status=BookingStatus.STORED)
    services.send_reminders(today=TODAY)
    assert {log.booking for log in ReminderLog.objects.all()} == {stored}


def test_reminder_days_setting_is_used(mailoutbox):
    set_settings(reminder_days_before_end=7)
    booking_ending(TODAY + datetime.timedelta(days=10))
    assert services.send_reminders(today=TODAY).outcomes == []


# --- Sent once only, catch-up, dry run ---------------------------------------------


def test_reminders_are_sent_only_once(mailoutbox):
    booking_ending(TODAY + datetime.timedelta(days=5))
    first = services.send_reminders(today=TODAY)
    assert first.sent == 2  # client + admins
    assert len(mailoutbox) == 2
    second = services.send_reminders(today=TODAY)
    third = services.send_reminders(today=TODAY + datetime.timedelta(days=1))
    assert second.outcomes == third.outcomes == []
    assert len(mailoutbox) == 2


def test_catch_up_after_the_job_was_down(mailoutbox):
    # The reminder should have gone out on 1 March (14 days before the end); the job only
    # runs again on 10 March: the booking is still in the window, so it gets its reminder.
    booking = booking_ending(D(2027, 3, 15))
    services.send_reminders(today=TODAY)
    assert ReminderLog.objects.filter(booking=booking, success=True).count() == 2


def test_dry_run_sends_and_logs_nothing(mailoutbox):
    booking_ending(TODAY + datetime.timedelta(days=5))
    report = services.send_reminders(today=TODAY, dry_run=True)
    assert len(report.outcomes) == 2
    assert mailoutbox == []
    assert not ReminderLog.objects.exists()


def test_failure_is_logged_and_retried(mailoutbox):
    booking = booking_ending(TODAY + datetime.timedelta(days=5))
    with mock.patch(
        "reminders.services._send", side_effect=smtplib.SMTPException("serveur indisponible")
    ):
        report = services.send_reminders(today=TODAY)
    assert report.failed == 2
    log = ReminderLog.objects.get(booking=booking, kind=ReminderKind.CLIENT_END_NOTICE)
    assert not log.success and log.error_message == "serveur indisponible"

    report = services.send_reminders(today=TODAY)
    assert report.sent == 2
    assert ReminderLog.objects.filter(booking=booking, success=True).count() == 2
    assert ReminderLog.objects.filter(booking=booking).count() == 4  # history kept


def test_no_admin_email_configured(mailoutbox):
    set_settings(admin_notification_emails="")
    booking_ending(TODAY + datetime.timedelta(days=5))
    report = services.send_reminders(today=TODAY)
    assert [o.kind for o in report.outcomes] == [ReminderKind.CLIENT_END_NOTICE]
    assert "Aucun email d'administrateur" in report.warnings[0]


# --- Email contents ----------------------------------------------------------------


def test_client_email_uses_the_template_and_placeholders(mailoutbox):
    client = make_client(first_name="Marie", last_name="Lambert", email="marie@example.be")
    booking_ending(
        D(2027, 3, 20), client=client, row=make_row("R07"), vehicle_fields={"plate": "AB-123-CD"}
    )
    set_settings(
        client_reminder_subject="Fin le {date_fin} pour {plaque}",
        client_reminder_body="Bonjour {client_nom}, {plaque} ({rangee}) jusqu'au {date_fin}. "
        "{societe_nom} – {societe_telephone} – {societe_email}",
    )
    services.send_reminders(today=TODAY)
    (message,) = emails_to(mailoutbox, "marie@example.be")
    assert message.subject == "Fin le 20/03/2027 pour AB-123-CD"
    assert message.body == (
        "Bonjour Marie Lambert, AB-123-CD (R07) jusqu'au 20/03/2027. "
        "Stockage Ardennes – 063 12 34 56 – contact@stockage.be"
    )
    assert message.from_email == "contact@stockage.be"
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    assert "<p>Bonjour Marie Lambert" in html


def test_default_client_text(mailoutbox):
    booking_ending(D(2027, 3, 20), vehicle_fields={"plate": "AB-123-CD"})
    services.send_reminders(today=TODAY)
    message = next(m for m in mailoutbox if "stockage.be" not in m.to[0])
    assert message.subject == "Fin de stockage de votre camping-car AB-123-CD le 20/03/2027"
    assert "prolonger" in message.body and "063 12 34 56" in message.body


def test_admin_email_contains_the_move_plan_when_exit_is_blocked(mailoutbox):
    row = make_row("R03")
    deep = booking_ending(
        D(2027, 3, 20), position=2, row=row, vehicle_fields={"plate": "AB-123-CD"}
    )
    make_booking(row, 1, deep.start_date, periods=3, vehicle=make_vehicle(plate="XY-987-ZZ"))
    services.send_reminders(today=TODAY)
    admin_message = next(
        m for m in emails_to(mailoutbox, "marie@stockage.be") if "AB-123-CD" in m.subject
    )
    assert admin_message.to == ["marie@stockage.be", "paul@stockage.be"]
    assert "sortie bloquée" in admin_message.subject
    assert "SORTIE BLOQUÉE" in admin_message.body
    assert (
        "Pour sortir AB-123-CD (position 2) le 20/03/2027 : déplacer d'abord XY-987-ZZ (pos. 1)."
        in admin_message.body
    )
    assert "dans 10 jours" in admin_message.body
    assert "Rappel envoyé au client : oui" in admin_message.body


def test_admin_email_without_blocking(mailoutbox):
    booking_ending(D(2027, 3, 20), vehicle_fields={"plate": "AB-123-CD"})
    services.send_reminders(today=TODAY)
    admin_message = emails_to(mailoutbox, "marie@stockage.be")[0]
    assert "bloquée" not in admin_message.subject
    assert "La sortie n'est pas bloquée." in admin_message.body


# --- Daily digest of blocked entries -----------------------------------------------


def test_digest_lists_blocked_entries_once_a_day(mailoutbox):
    row = make_row("R05")
    make_booking(row, 1, D(2027, 3, 1), periods=4, vehicle=make_vehicle(plate="XY-987-ZZ"))
    make_booking(row, 2, D(2027, 3, 15), periods=1, vehicle=make_vehicle(plate="AB-123-CD"))
    services.send_reminders(today=TODAY)
    digests = [m for m in mailoutbox if "entrée(s) bloquée(s)" in m.subject]
    assert len(digests) == 1
    assert "Pour rentrer AB-123-CD (position 2) le 15/03/2027" in digests[0].body

    services.send_reminders(today=TODAY)  # same day: not again
    assert len([m for m in mailoutbox if "entrée(s) bloquée(s)" in m.subject]) == 1
    services.send_reminders(today=TODAY + datetime.timedelta(days=1))  # next day: again
    assert len([m for m in mailoutbox if "entrée(s) bloquée(s)" in m.subject]) == 2


def test_no_digest_when_nothing_is_blocked(mailoutbox):
    row = make_row("R05")
    make_booking(row, 1, D(2027, 3, 15), periods=1)
    services.send_reminders(today=TODAY)
    assert not [m for m in mailoutbox if "bloquée" in m.subject]
    assert not ReminderLog.objects.filter(kind=ReminderKind.ENTRY_DIGEST).exists()


# --- Command and screens -------------------------------------------------------------


def test_command_dry_run_and_real_run(mailoutbox):
    booking_ending(TODAY + datetime.timedelta(days=5), vehicle_fields={"plate": "AB-123-CD"})
    out = StringIO()
    call_command("send_reminders", "--dry-run", "--date", "2027-03-10", stdout=out)
    assert "[simulation]" in out.getvalue() and "AB-123-CD" in out.getvalue()
    assert mailoutbox == []

    out = StringIO()
    call_command("send_reminders", "--date", "2027-03-10", stdout=out)
    assert "2 email(s) envoyé(s), 0 échec(s)." in out.getvalue()

    out = StringIO()
    call_command("send_reminders", "--date", "2027-03-10", stdout=out)
    assert "Aucun rappel à envoyer le 10/03/2027." in out.getvalue()


def test_command_rejects_bad_date():
    from django.core.management import CommandError

    with pytest.raises(CommandError, match="Date invalide"):
        call_command("send_reminders", "--date", "10/03/2027")


def test_booking_detail_shows_reminder_history(admin_client, mailoutbox):
    booking = booking_ending(TODAY + datetime.timedelta(days=5))
    url = reverse("storage:booking_detail", args=[booking.pk])
    assert "Aucun rappel envoyé" in admin_client.get(url).content.decode()
    services.send_reminders(today=TODAY)
    content = admin_client.get(url).content.decode()
    assert "Rappel de fin au client" in content
    assert "Rappel de fin aux administrateurs" in content
    assert "envoyé" in content


def test_database_refuses_a_second_successful_log():
    from django.db import IntegrityError, transaction

    booking = booking_ending(TODAY)
    ReminderLog.objects.create(
        booking=booking, kind=ReminderKind.CLIENT_END_NOTICE, recipients="a", success=True
    )
    ReminderLog.objects.create(
        booking=booking, kind=ReminderKind.CLIENT_END_NOTICE, recipients="a", success=False
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ReminderLog.objects.create(
            booking=booking, kind=ReminderKind.CLIENT_END_NOTICE, recipients="a", success=True
        )
    ReminderLog.objects.create(
        kind=ReminderKind.ENTRY_DIGEST, digest_date=TODAY, recipients="a", success=True
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ReminderLog.objects.create(
            kind=ReminderKind.ENTRY_DIGEST, digest_date=TODAY, recipients="a", success=True
        )
