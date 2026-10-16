"""seed_demo: demo data for development, never in production."""

import pytest
from django.core.management import CommandError, call_command

from clients.models import Client
from invoicing import services
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
    invoice = services.issue_invoice(services.create_invoice_for_booking(Booking.objects.first()))
    call_command("seed_demo", reset=True)
    assert not Invoice.objects.filter(pk=invoice.pk).exists()
    assert Row.objects.count() == 40


def test_reset_never_deletes_issued_invoices_in_production(settings, media):
    settings.DEBUG = True
    call_command("seed_demo")
    services.issue_invoice(services.create_invoice_for_booking(Booking.objects.first()))
    settings.DEBUG = False
    with pytest.raises(CommandError, match="factures émises"):
        call_command("seed_demo", reset=True, force=True)
    assert Invoice.objects.exclude(number=None).exists()
