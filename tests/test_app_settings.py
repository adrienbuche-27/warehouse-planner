"""M1: AppSettings singleton and the Paramètres page."""

import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.models import model_to_dict
from django.urls import reverse
from PIL import Image

from core.forms import SETTINGS_GROUPS, AppSettingsForm
from core.models import DEFAULT_REMINDER_BODY, AppSettings

pytestmark = pytest.mark.django_db


def valid_settings_data(**overrides):
    """POST data for the settings form: the current values, with a price set."""
    values = model_to_dict(AppSettings.load(), fields=AppSettingsForm._meta.fields)
    data = {name: "" if value is None else value for name, value in values.items()}
    data.pop("company_logo")
    data["price_per_period"] = "45.00"
    data.update(overrides)
    return data


# --- Model -------------------------------------------------------------------


def test_load_creates_settings_with_defaults():
    app_settings = AppSettings.load()
    assert app_settings.default_row_length_m == Decimal("16.00")
    assert app_settings.vehicle_gap_m == Decimal("0.50")
    assert app_settings.period_days == 14
    assert app_settings.price_per_period is None
    assert app_settings.vat_regime == "standard"
    assert app_settings.vat_rate == Decimal("21.00")
    assert app_settings.reminder_days_before_end == 14
    assert app_settings.payment_terms_days == 30
    assert app_settings.client_reminder_body == DEFAULT_REMINDER_BODY


def test_only_one_settings_row_can_exist():
    AppSettings.load()
    AppSettings(price_per_period=Decimal("10")).save()
    assert AppSettings.objects.count() == 1
    assert AppSettings.load().price_per_period == Decimal("10")


def test_settings_cannot_be_deleted():
    app_settings = AppSettings.load()
    with pytest.raises(ValidationError):
        app_settings.delete()
    assert AppSettings.objects.count() == 1


def test_identifiers_are_stored_normalised():
    app_settings = AppSettings.load()
    app_settings.company_vat_number = "be 0123.456.789"
    app_settings.company_iban = "be68 5390 0754 7034"
    app_settings.company_bic = "gebabebb"
    app_settings.save()
    app_settings.refresh_from_db()
    assert app_settings.company_vat_number == "BE0123456789"
    assert app_settings.company_iban == "BE68539007547034"
    assert app_settings.company_bic == "GEBABEBB"


def test_admin_emails_and_sender(settings):
    settings.DEFAULT_FROM_EMAIL = "noreply@example.be"
    app_settings = AppSettings.load()
    app_settings.admin_notification_emails = "a@example.be, b@example.be"
    assert app_settings.admin_emails == ["a@example.be", "b@example.be"]
    assert app_settings.sender_email == "noreply@example.be"
    app_settings.company_email = "contact@example.be"
    assert app_settings.sender_email == "contact@example.be"


def test_default_reminder_texts_are_valid_templates():
    AppSettings.load().full_clean()


def test_form_groups_cover_every_field():
    model_fields = {field.name for field in AppSettings._meta.get_fields() if field.name != "id"}
    grouped = {name for _, names in SETTINGS_GROUPS for name in names}
    assert grouped == model_fields


# --- Paramètres page ---------------------------------------------------------


def test_settings_page_requires_login(client):
    response = client.get(reverse("core:settings"))
    assert response.status_code == 302


def test_settings_page_shows_groups_and_notice(admin_client):
    response = admin_client.get(reverse("core:settings"))
    assert response.status_code == 200
    content = response.content.decode()
    for title in ["Entrepôt", "Tarifs &amp; TVA", "Société (mentions sur factures)", "Rappels"]:
        assert title in content
    assert "nouvelles réservations" in content
    assert "Envoyer un email de test" in content
    assert 'aria-current="page">Paramètres' in content


def test_settings_can_be_saved(admin_client):
    data = valid_settings_data(
        default_row_length_m="15.50",
        vehicle_gap_m="0.60",
        company_name="Stockage Ardennes",
        company_vat_number="BE 0123.456.789",
        company_iban="BE68 5390 0754 7034",
        admin_notification_emails="marie@example.be",
    )
    response = admin_client.post(reverse("core:settings"), data)
    assert response.status_code == 302
    app_settings = AppSettings.load()
    assert app_settings.default_row_length_m == Decimal("15.50")
    assert app_settings.vehicle_gap_m == Decimal("0.60")
    assert app_settings.price_per_period == Decimal("45.00")
    assert app_settings.company_vat_number == "BE0123456789"


def test_price_is_required_on_the_form(admin_client):
    response = admin_client.post(reverse("core:settings"), valid_settings_data(price_per_period=""))
    assert response.status_code == 200
    assert "n&#x27;ont pas été enregistrés" in response.content.decode()
    assert AppSettings.load().price_per_period is None


def test_invalid_values_are_reported(admin_client):
    data = valid_settings_data(
        company_iban="BE68 5390 0754 7035",
        client_reminder_body="Bonjour {nom}",
    )
    response = admin_client.post(reverse("core:settings"), data)
    content = response.content.decode()
    assert "chiffres de contrôle" in content
    assert "Variable inconnue" in content
    assert 'aria-invalid="true"' in content


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


def test_logo_upload_preview_and_removal(admin_client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    assert admin_client.get(reverse("core:settings_logo")).status_code == 404

    logo = SimpleUploadedFile("logo.png", _png_bytes(), content_type="image/png")
    response = admin_client.post(reverse("core:settings"), valid_settings_data(company_logo=logo))
    assert response.status_code == 302
    assert AppSettings.load().company_logo.name.startswith("company/")

    response = admin_client.get(reverse("core:settings_logo"))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == _png_bytes()

    data = valid_settings_data(**{"company_logo-clear": "on"})
    admin_client.post(reverse("core:settings"), data)
    assert not AppSettings.load().company_logo


def test_logo_is_not_public(client):
    response = client.get(reverse("core:settings_logo"))
    assert response.status_code == 302


# --- Test email --------------------------------------------------------------


def test_test_email_goes_to_logged_in_user(client, django_user_model, mailoutbox):
    user = django_user_model.objects.create_superuser("marie", "marie@example.be", "pw-solide-123")
    client.force_login(user)
    app_settings = AppSettings.load()
    app_settings.company_email = "contact@example.be"
    app_settings.save()

    response = client.post(reverse("core:settings_test_email"))
    assert response.status_code == 302
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["marie@example.be"]
    assert mailoutbox[0].from_email == "contact@example.be"


def test_test_email_falls_back_to_admin_emails(client, django_user_model, mailoutbox):
    user = django_user_model.objects.create_superuser("paul", "", "pw-solide-123")
    client.force_login(user)
    app_settings = AppSettings.load()
    app_settings.admin_notification_emails = "a@example.be, b@example.be"
    app_settings.save()

    client.post(reverse("core:settings_test_email"))
    assert mailoutbox[0].to == ["a@example.be", "b@example.be"]


def test_test_email_without_recipient_shows_error(client, django_user_model, mailoutbox):
    user = django_user_model.objects.create_superuser("paul", "", "pw-solide-123")
    client.force_login(user)
    response = client.post(reverse("core:settings_test_email"), follow=True)
    assert mailoutbox == []
    assert "Aucun destinataire" in response.content.decode()


def test_test_email_reports_smtp_failure(admin_client, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST = "127.0.0.1"
    settings.EMAIL_PORT = 1  # nothing listens here
    response = admin_client.post(reverse("core:settings_test_email"), follow=True)
    assert "L&#x27;envoi a échoué" in response.content.decode()


def test_test_email_requires_post(admin_client):
    assert admin_client.get(reverse("core:settings_test_email")).status_code == 405
