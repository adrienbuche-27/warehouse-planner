"""M0: the app boots, everything is behind login, and the UI is in French."""

import os
import subprocess
import sys

import pytest
from django.conf import settings
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


def test_french_even_when_the_browser_asks_for_english(admin_client):
    response = admin_client.post(
        reverse("clients:client_create"), {"client_type": "private"}, HTTP_ACCEPT_LANGUAGE="en-US"
    )
    content = response.content.decode()
    assert "Ce champ est obligatoire." in content
    assert "This field is required." not in content


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


def _allowed_hosts_with_env(**env_vars):
    """Import the real settings in a fresh process with the given environment variables."""
    env = {**os.environ, "DJANGO_SECRET_KEY": "x", **env_vars}
    output = subprocess.check_output(
        [sys.executable, "-c", "import config.settings as s; print(','.join(s.ALLOWED_HOSTS))"],
        env=env,
        cwd=settings.BASE_DIR,
        text=True,
    )
    return output.strip().split(",")


def test_debug_allows_localhost_even_when_hosts_are_configured():
    # Reproduces `cp .env.example .env` + DJANGO_DEBUG=True, which keeps the example domain.
    hosts = _allowed_hosts_with_env(DJANGO_DEBUG="True", DJANGO_ALLOWED_HOSTS="stockage.example.be")
    assert {"stockage.example.be", "localhost", "127.0.0.1"} <= set(hosts)


def test_production_only_allows_configured_hosts():
    hosts = _allowed_hosts_with_env(
        DJANGO_DEBUG="False", DJANGO_ALLOWED_HOSTS="stockage.example.be"
    )
    assert hosts == ["stockage.example.be"]


def test_missing_page_shows_french_404(admin_client):
    # E.g. a client deleted by "seed_demo --reset": record numbers are never reused.
    response = admin_client.get("/clients/999999/")
    assert response.status_code == 404
    content = response.content.decode()
    assert "Page introuvable" in content
    assert "Tableau de bord" in content


def test_unknown_url_for_anonymous_visitor_is_a_plain_404(client):
    response = client.get("/nexiste-pas/")
    assert response.status_code == 404
    assert "Page introuvable" in response.content.decode()


def test_favicon_redirects_to_logo_without_login(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 302
    assert response.url.endswith("img/logo-placeholder.svg")


def _setting_with_env(name, **env_vars):
    env = {**os.environ, "DJANGO_SECRET_KEY": "x", **env_vars}
    output = subprocess.check_output(
        # Django's own default applies when the settings file does not define the name.
        [sys.executable, "-c", f"import config.settings as s; print(getattr(s, '{name}', False))"],
        env=env,
        cwd=settings.BASE_DIR,
        text=True,
    )
    return output.strip()


def test_empty_backup_dir_falls_back_to_the_project_backups_folder():
    assert _setting_with_env("BACKUP_DIR", BACKUP_DIR="") == str(settings.BASE_DIR / "backups")
    assert (
        _setting_with_env("BACKUP_DIR", BACKUP_DIR="/srv/cloud/Sauvegardes")
        == "/srv/cloud/Sauvegardes"
    )


def test_local_mode_does_not_require_https_cookies():
    assert _setting_with_env("SESSION_COOKIE_SECURE", DJANGO_DEBUG="False") == "False"
    assert (
        _setting_with_env("SESSION_COOKIE_SECURE", DJANGO_DEBUG="False", DJANGO_HTTPS="True")
        == "True"
    )


def test_whitenoise_serves_static_files():
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in settings.MIDDLEWARE
