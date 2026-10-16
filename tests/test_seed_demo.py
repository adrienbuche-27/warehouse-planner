"""seed_demo: demo data for development, never in production."""

import pytest
from django.core.management import CommandError, call_command

from clients.models import Client
from invoicing.models import Invoice
from storage.models import Booking, Row

pytestmark = pytest.mark.django_db


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def test_seed_demo_creates_data(settings, media):
    settings.DEBUG = True
    call_command("seed_demo")
    assert Row.objects.count() == 40
    assert Client.objects.count() == 60
    assert Booking.objects.count() > 0


def test_seed_demo_refuses_when_debug_is_off(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="production"):
        call_command("seed_demo")


def test_seed_demo_refuses_existing_data_without_reset(settings, media):
    settings.DEBUG = True
    call_command("seed_demo")
    with pytest.raises(CommandError, match="--reset"):
        call_command("seed_demo")


def test_reset_also_removes_invoices_in_development(settings, media):
    settings.DEBUG = True
    call_command("seed_demo")
    old_invoices = set(Invoice.objects.values_list("pk", flat=True))
    assert old_invoices  # seed_demo issues invoices for the bookings that have started
    call_command("seed_demo", reset=True)
    assert not Invoice.objects.filter(pk__in=old_invoices).exists()
    assert Row.objects.count() == 40


def test_reset_never_deletes_issued_invoices_in_production(settings, media):
    settings.DEBUG = True
    call_command("seed_demo")  # issues invoices
    settings.DEBUG = False
    with pytest.raises(CommandError, match="factures émises"):
        call_command("seed_demo", reset=True, force=True)
    assert Invoice.objects.exclude(number=None).exists()


def test_seed_demo_feeds_the_dashboard(settings, media):
    import datetime

    from core import dashboard

    settings.DEBUG = True
    call_command("seed_demo")
    today = datetime.date.today()
    assert Invoice.objects.exclude(number=None).exists()
    assert any(amount for _, amount in dashboard.monthly_revenue(today))
    assert dashboard.occupancy_on(today).vehicles > 0
