"""M0: the app boots, everything is behind login, and the UI is in French."""

import pytest
from django.db import connection
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_login_page_is_public_and_in_french(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Connexion" in content
    assert "Mot de passe oublié" in content


def test_dashboard_requires_login(client):
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_dashboard_shows_navigation_when_logged_in(admin_client):
    response = admin_client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    content = response.content.decode()
    for label in [
        "Tableau de bord",
        "Planning",
        "Réservations",
        "Clients",
        "Véhicules",
        "Factures",
        "Paramètres",
    ]:
        assert label in content
    assert "htmx.min.js" in content
    assert "pico.min.css" in content


def test_login_redirects_to_dashboard(client, django_user_model):
    django_user_model.objects.create_user(username="marie", password="un-mot-de-passe-solide")
    response = client.post(
        reverse("login"), {"username": "marie", "password": "un-mot-de-passe-solide"}
    )
    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")


def test_wrong_password_shows_french_error(client):
    response = client.post(reverse("login"), {"username": "nobody", "password": "wrong"})
    assert response.status_code == 200
    assert "incorrect" in response.content.decode()


def test_logout_requires_post_and_redirects_to_login(admin_client):
    response = admin_client.post(reverse("logout"))
    assert response.status_code == 302
    assert response.url == reverse("login")


def test_password_reset_sends_french_email(client, django_user_model, mailoutbox):
    django_user_model.objects.create_user(
        username="marie", email="marie@example.be", password="un-mot-de-passe-solide"
    )
    response = client.post(reverse("password_reset"), {"email": "marie@example.be"})
    assert response.status_code == 302
    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject == "Réinitialisation de votre mot de passe"
    assert "/compte/reset/" in mailoutbox[0].body


def test_admin_is_available_for_superusers(admin_client):
    response = admin_client.get("/admin/")
    assert response.status_code == 200


def test_locale_settings(settings):
    assert settings.LANGUAGE_CODE == "fr-be"
    assert settings.TIME_ZONE == "Europe/Brussels"
    assert settings.USE_TZ is True


def test_sqlite_pragmas_are_set_on_connection():
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1
        cursor.execute("PRAGMA busy_timeout")
        assert cursor.fetchone()[0] == 5000
