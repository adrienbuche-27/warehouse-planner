"""
Django settings for the camping-car storage app.

All secrets and environment-specific values come from environment variables,
usually loaded from a `.env` file at the project root (see `.env.example`).
"""

import warnings
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DJANGO_DEBUG")

# The secret key is mandatory in production. A throwaway key is only allowed in DEBUG mode.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in the .env file (see .env.example).")
    SECRET_KEY = "insecure-dev-key-do-not-use-in-production"

# The app is used on the computer it runs on: localhost is the default.
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS") or ["localhost", "127.0.0.1"]
if DEBUG:
    # In development, the local addresses always work, whatever .env contains.
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, "localhost", "127.0.0.1", "[::1]"]
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Project apps
    "core",
    "clients",
    "storage",
    "invoicing",
    "reminders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the CSS / JavaScript files (collected in staticfiles/) when DEBUG is off.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every view requires login, except those marked with @login_not_required
    # (Django's own login and password-reset views already are).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: a single SQLite file.
# WAL mode lets readers and a writer work at the same time; busy_timeout makes a
# connection wait (up to 5 s) instead of failing when the database is locked.
# Django already turns on foreign key enforcement for SQLite.
# "IMMEDIATE" transactions take the write lock at the start of each transaction,
# which avoids "database is locked" errors halfway through a write.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("DJANGO_DB_PATH", default=str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA foreign_keys=ON;"
                "PRAGMA busy_timeout=5000;"
            ),
            "transaction_mode": "IMMEDIATE",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Authentication

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "login"


# Localisation: French (Belgium), Brussels time.
# The whole app is in French whatever the browser's language: there is deliberately no
# LocaleMiddleware, which would switch Django's own messages ("Ce champ est obligatoire.")
# and number formats to the browser's language.
# Date and number formats are overridden in config/formats/fr/formats.py.

LANGUAGE_CODE = "fr-be"
TIME_ZONE = "Europe/Brussels"
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ["config.formats"]


# Static files (CSS, JavaScript, images) and uploaded / generated files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # filled by "manage.py collectstatic"
if DEBUG:
    # In development the files are served straight from static/: no collectstatic needed,
    # so WhiteNoise's warning about the missing staticfiles/ folder is irrelevant.
    WHITENOISE_USE_FINDERS = True
    warnings.filterwarnings("ignore", message="No directory at", module="whitenoise.base")

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# Email. Without EMAIL_HOST, emails are printed to the console (handy in development).

EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="webmaster@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)


# HTTPS. The app runs on a single computer and only listens on 127.0.0.1 (waitress, see
# deploy/windows/): nothing travels over the network, so it is used over plain http://localhost
# and cookies cannot be marked "secure". Set DJANGO_HTTPS=True only if the app is one day put
# behind an HTTPS reverse proxy.

HTTPS = env.bool("DJANGO_HTTPS", default=False)
if HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
else:
    # "manage.py check --deploy" warnings that only make sense with HTTPS.
    SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008", "security.W012", "security.W016"]


# Port of the local web server (deploy/windows/run_server.py): http://localhost:8000.

APP_PORT = env.int("APP_PORT", default=8000)


# Backups (manage.py backup_data): a folder outside the project, ideally synced to the cloud
# (OneDrive, Google Drive, Dropbox...). Never put the live database itself in a synced folder.

BACKUP_DIR = Path(env("BACKUP_DIR", default="") or BASE_DIR / "backups")  # empty = default
BACKUP_KEEP_DAYS = env.int("BACKUP_KEEP_DAYS", default=30)


# Logging: everything at INFO level and above goes to the console. On the Windows computer the
# scripts in deploy/windows/ write it to the logs/ folder.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # PDF generation libraries are very talkative: keep only their warnings.
    "loggers": {
        "weasyprint": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
    },
}
