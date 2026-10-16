"""M1: rows, their effective length and bulk creation."""

from decimal import Decimal

import pytest
from django.urls import reverse

from core.models import AppSettings
from storage.models import Row
from storage.services import create_rows

pytestmark = pytest.mark.django_db


def test_effective_length_uses_override_or_settings_default():
    app_settings = AppSettings.load()
    row_default = Row.objects.create(code="R01")
    row_override = Row.objects.create(code="R02", length_override_m=Decimal("12.00"))
    assert row_default.effective_length == Decimal("16.00")
    assert row_override.effective_length == Decimal("12.00")

    # Propagation: changing the default length changes every row without an override.
    app_settings.default_row_length_m = Decimal("18.00")
    app_settings.save()
    assert row_default.effective_length == Decimal("18.00")
    assert row_override.effective_length == Decimal("12.00")


def test_create_rows_from_scratch():
    rows = create_rows(3)
    assert [row.code for row in rows] == ["R01", "R02", "R03"]
    assert [row.display_order for row in Row.objects.all()] == [1, 2, 3]
    assert all(row.is_active and row.length_override_m is None for row in Row.objects.all())


def test_create_rows_continues_after_existing_rows():
    create_rows(10)
    rows = create_rows(2)
    assert [row.code for row in rows] == ["R11", "R12"]
    assert Row.objects.count() == 12


def test_create_rows_ignores_custom_codes_and_goes_past_99():
    Row.objects.create(code="ATELIER", display_order=5)
    Row.objects.create(code="R98", display_order=6)
    rows = create_rows(3)
    assert [row.code for row in rows] == ["R99", "R100", "R101"]
    assert [row.display_order for row in rows] == [7, 8, 9]


@pytest.mark.parametrize("count", [0, -1, 201])
def test_create_rows_rejects_bad_counts(count):
    with pytest.raises(ValueError):
        create_rows(count)


# --- Views -------------------------------------------------------------------


def test_bulk_create_view(admin_client):
    response = admin_client.post(reverse("storage:row_bulk_create"), {"count": "5"}, follow=True)
    assert Row.objects.count() == 5
    content = response.content.decode()
    assert "5 rangée(s) créée(s) : R01 à R05." in content
    assert "R05" in content


def test_bulk_create_view_rejects_invalid_count(admin_client):
    response = admin_client.post(reverse("storage:row_bulk_create"), {"count": "0"}, follow=True)
    assert Row.objects.count() == 0
    assert "Nombre de rangées invalide" in response.content.decode()


def test_row_inline_edit_form(admin_client):
    row = Row.objects.create(code="R01")
    response = admin_client.get(reverse("storage:row_edit", args=[row.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert content.strip().startswith('<tr id="row-')
    assert 'name="length_override_m"' in content


def test_row_inline_edit_saves(admin_client):
    row = Row.objects.create(code="R01", display_order=1)
    data = {"code": "r01b", "display_order": "3", "length_override_m": "14.5", "notes": "Porte"}
    response = admin_client.post(reverse("storage:row_edit", args=[row.pk]), data)
    assert response.status_code == 200
    row.refresh_from_db()
    assert row.code == "R01B"
    assert row.length_override_m == Decimal("14.50")
    assert row.is_active is False  # unchecked checkbox
    assert "14,50 m" in response.content.decode()


def test_row_inline_edit_rejects_duplicate_code(admin_client):
    Row.objects.create(code="R01")
    row = Row.objects.create(code="R02")
    data = {"code": "R01", "display_order": "2", "is_active": "on"}
    response = admin_client.post(reverse("storage:row_edit", args=[row.pk]), data)
    assert response.status_code == 200
    assert "Une rangée avec ce code existe déjà." in response.content.decode()
    row.refresh_from_db()
    assert row.code == "R02"


def test_row_display_partial(admin_client):
    row = Row.objects.create(code="R07")
    response = admin_client.get(reverse("storage:row_display", args=[row.pk]))
    content = response.content.decode()
    assert "R07" in content
    assert "16,00 m" in content


def test_settings_page_lists_rows_with_effective_length(admin_client):
    Row.objects.create(code="R01")
    Row.objects.create(code="R02", length_override_m=Decimal("12"))
    content = admin_client.get(reverse("core:settings")).content.decode()
    assert "R01" in content and "R02" in content
    assert "16,00 m" in content and "12,00 m" in content
