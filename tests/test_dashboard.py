"""M7: dashboard figures, charts and the reminders history page."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from core import charts, dashboard
from invoicing import services as invoicing
from reminders import services as reminders
from reminders.models import ReminderKind, ReminderLog
from storage.models import BookingStatus
from tests.factories import FLAT_PRICE, make_booking, make_row, make_vehicle, set_settings
from tests.test_invoicing import COMPANY

pytestmark = pytest.mark.django_db

D = datetime.date
TODAY = D(2027, 3, 10)  # a Wednesday


@pytest.fixture(autouse=True)
def demo_settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    set_settings(
        **FLAT_PRICE,
        default_row_length_m=Decimal("16.00"),
        vehicle_gap_m=Decimal("0.50"),
        admin_notification_emails="admin@stockage.be",
        **COMPANY,
    )


# --- KPIs --------------------------------------------------------------------------


def test_occupancy_today():
    first, second = make_row("R01"), make_row("R02")
    make_row("R03", is_active=False)
    make_booking(first, 1, D(2027, 3, 1), length="8")
    make_booking(first, 2, D(2027, 3, 5), length="7")
    make_booking(second, 1, D(2027, 3, 11), length="6")  # tomorrow: not counted
    make_booking(second, 2, D(2027, 3, 1), length="6", status=BookingStatus.CANCELLED)
    result = dashboard.occupancy_on(TODAY)
    assert result.used_m == Decimal("15.5")  # 8 + 0,5 + 7
    assert result.total_m == Decimal("32")
    assert result.free_m == Decimal("16.5")
    assert result.vehicles == 2
    assert round(result.percent) == 48


def test_invoice_figures_net_of_partial_credit_notes():
    row = make_row()
    unpaid = invoicing.issue_invoice(
        invoicing.create_invoice_for_booking(make_booking(row, 1, D(2027, 1, 4), periods=2)),
        issue_date=D(2027, 1, 4),
    )  # due 03/02: overdue on 10/03
    recent = invoicing.issue_invoice(
        invoicing.create_invoice_for_booking(make_booking(row, 2, D(2027, 3, 1), periods=2)),
        issue_date=D(2027, 3, 1),
    )
    paid = invoicing.issue_invoice(
        invoicing.create_invoice_for_booking(make_booking(row, 3, D(2027, 2, 1))),
        issue_date=D(2027, 2, 1),
    )
    invoicing.mark_paid(paid, D(2027, 2, 5), "cash")
    credit = invoicing.create_credit_note(recent, "Une période")
    line = credit.lines.get()
    line.quantity = 1
    line.save()
    invoicing.issue_credit_note(credit, issue_date=D(2027, 3, 2))

    figures = dashboard.invoice_figures(TODAY)
    assert figures.unpaid_count == 2
    assert figures.unpaid_amount == unpaid.total_incl_vat + Decimal("54.45")
    assert (figures.overdue_count, figures.overdue_amount) == (1, unpaid.total_incl_vat)


# --- Lists ---------------------------------------------------------------------------


def test_ending_soon_with_reminder_and_blocking(mailoutbox):
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    deep = make_booking(row, 2, D(2027, 3, 1), periods=1, vehicle=make_vehicle(plate="AB-123-CD"))
    make_booking(row, 1, D(2027, 3, 1), periods=3)  # blocks the exit of `deep`
    make_booking(row, 3, D(2027, 2, 1), periods=6)  # ends 25/04: too far
    reminders.send_reminders(today=TODAY)
    items = dashboard.ending_soon(TODAY)
    assert [item.booking for item in items] == [deep]
    assert items[0].reminder_sent
    assert items[0].blockers


def test_upcoming_entries_with_blocked_entry():
    set_settings(default_row_length_m=Decimal("30.00"))
    row = make_row("R01")
    make_booking(row, 1, D(2027, 3, 1), periods=4)
    blocked = make_booking(row, 2, D(2027, 3, 15), periods=1)
    free = make_booking(make_row("R02"), 1, D(2027, 3, 20), periods=1)
    make_booking(make_row("R03"), 1, D(2027, 3, 30), periods=1)  # beyond 14 days
    items = dashboard.upcoming_entries(TODAY)
    assert [item.booking for item in items] == [blocked, free]
    assert items[0].blockers and not items[1].blockers


def test_failed_reminders_disappear_once_sent():
    booking = make_booking(make_row(), 1, D(2027, 3, 1))
    failure = ReminderLog.objects.create(
        booking=booking, kind=ReminderKind.CLIENT_END_NOTICE, recipients="x", error_message="refusé"
    )
    assert dashboard.failed_reminders(datetime.date.today()) == [failure]
    ReminderLog.objects.create(
        booking=booking, kind=ReminderKind.CLIENT_END_NOTICE, recipients="x", success=True
    )
    assert dashboard.failed_reminders(datetime.date.today()) == []


# --- Charts --------------------------------------------------------------------------


def test_forecast_chart_has_12_windows_in_percent():
    row = make_row("R01")
    make_booking(row, 1, D(2027, 3, 8), periods=2, length="8")  # windows 1 and 2
    chart = dashboard.occupancy_forecast_chart(TODAY)
    assert len(chart.bars) == 12
    assert [bar.value for bar in chart.bars[:3]] == [Decimal(50), Decimal(50), Decimal(0)]
    assert chart.bars[0].label == "08/03"
    assert "50 %" in chart.bars[0].tooltip
    assert [line.label for line in chart.reference_lines] == ["70 %", "95 %"]
    assert chart.ticks[-1].label == "100 %"


def test_monthly_revenue_last_12_months_net_of_credit_notes():
    row = make_row()
    january = invoicing.issue_invoice(
        invoicing.create_invoice_for_booking(make_booking(row, 1, D(2027, 1, 4), periods=2)),
        issue_date=D(2027, 1, 4),
    )
    invoicing.issue_invoice(
        invoicing.create_invoice_for_booking(make_booking(row, 2, D(2027, 3, 1))),
        issue_date=D(2027, 3, 1),
    )
    credit = invoicing.create_credit_note(january, "Erreur")
    invoicing.issue_credit_note(credit, issue_date=D(2027, 3, 2))
    invoicing.create_invoice_for_booking(make_booking(row, 3, D(2027, 3, 5)))  # draft: ignored

    data = dict(dashboard.monthly_revenue(TODAY))
    assert len(data) == 12
    assert min(data) == D(2026, 4, 1) and max(data) == D(2027, 3, 1)
    assert data[D(2027, 1, 1)] == Decimal("90.00")
    assert data[D(2027, 3, 1)] == Decimal("45.00") - Decimal("90.00")
    chart = dashboard.revenue_chart(TODAY)
    assert [bar.label for bar in chart.bars][-3:] == ["janv. 27", "févr.", "mars"]


def test_bar_chart_geometry():
    bars = [
        charts.Bar("a", Decimal(0), ""),
        charts.Bar("b", Decimal(50), ""),
        charts.Bar("c", Decimal(100), ""),
    ]
    chart = charts.bar_chart(bars, maximum=Decimal(100))
    assert bars[0].path == ""  # nothing drawn for 0
    assert bars[2].height == pytest.approx(2 * bars[1].height)
    assert bars[2].y == pytest.approx(charts.TOP)
    assert bars[1].x - (bars[0].x + bars[0].width) == pytest.approx(charts.GAP)
    assert [tick.label for tick in chart.ticks][0] == "0"


def test_nice_axis_maximum():
    assert charts._nice_maximum(Decimal("1234")) == 2000
    assert charts._nice_maximum(Decimal("87")) == 100
    assert charts._nice_maximum(Decimal("0")) == 1


# --- Pages ---------------------------------------------------------------------------


def test_dashboard_page(admin_client):
    row = make_row("R01")
    make_booking(row, 1, datetime.date.today(), length="8", vehicle=make_vehicle(plate="AB-123-CD"))
    response = admin_client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    content = response.content.decode()
    for text in [
        "Occupation aujourd'hui",
        "Espace libre",
        "Réservations en cours",
        "Factures impayées",
        "Factures en retard",
        "Fin de stockage dans les 14 prochains jours",
        "AB-123-CD",
        "Prochaines entrées",
        "Occupation prévue",
        "Chiffre d'affaires mensuel",
        'class="bar-chart"',
        "Voir les données",
        "Historique des rappels",
    ]:
        assert text in content, text
    assert response.context["occupancy"].vehicles == 1


def test_dashboard_without_rows(admin_client):
    content = admin_client.get(reverse("core:dashboard")).content.decode()
    assert "Aucune rangée active" in content


def test_dashboard_shows_failed_reminders(admin_client):
    booking = make_booking(make_row(), 1, D(2027, 3, 1), vehicle=make_vehicle(plate="AB-123-CD"))
    ReminderLog.objects.create(
        booking=booking, kind=ReminderKind.CLIENT_END_NOTICE, recipients="x", error_message="refusé"
    )
    content = admin_client.get(reverse("core:dashboard")).content.decode()
    assert "1 rappel n'a pas pu être envoyé" in content
    assert "refusé" in content


def test_reminder_history_page(admin_client, mailoutbox):
    booking = make_booking(
        make_row(), 1, TODAY + datetime.timedelta(days=-8), vehicle=make_vehicle(plate="AB-123-CD")
    )
    reminders.send_reminders(today=TODAY)
    ReminderLog.objects.create(
        kind=ReminderKind.ENTRY_DIGEST,
        digest_date=TODAY,
        recipients="admin@stockage.be",
        success=False,
        error_message="timeout",
    )
    url = reverse("reminders:reminder_list")
    response = admin_client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    assert "AB-123-CD" in content and "Rappel de fin au client" in content
    assert reverse("storage:booking_detail", args=[booking.pk]) in content
    assert response.context["page"].paginator.count == 3

    assert admin_client.get(url, {"resultat": "echec"}).context["page"].paginator.count == 1
    assert admin_client.get(url, {"type": "admin_end_notice"}).context["page"].paginator.count == 1
    assert admin_client.get(url, {"q": "ab-123"}).context["page"].paginator.count == 2
    response = admin_client.get(url, {"q": "ab-123"}, headers={"HX-Request": "true"})
    assert "<html" not in response.content.decode()


def test_reminder_history_requires_login(client):
    assert client.get(reverse("reminders:reminder_list")).status_code == 302


def test_chart_svg_uses_dots_not_french_commas(admin_client):
    import re

    make_booking(make_row("R01"), 1, datetime.date.today(), length="8")
    content = admin_client.get(reverse("core:dashboard")).content.decode()
    svg = content[content.index('<svg class="bar-chart"') : content.index("</svg>")]
    assert not re.search(r'(x|y|y1|y2|width|height)="\d+,\d', svg)


def test_compact_euro_axis_labels():
    assert dashboard._compact_euros(Decimal(0)) == "0 €"
    assert dashboard._compact_euros(Decimal(500)) == "500 €"
    assert dashboard._compact_euros(Decimal(1250)) == "1,25 k€"
    assert dashboard._compact_euros(Decimal(5000)) == "5 k€"
