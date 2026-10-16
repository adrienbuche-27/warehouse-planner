# Gestion Stockage Camping-Cars

Internal web app to manage a camping-car storage warehouse in Belgium: clients and vehicles,
space planning in 2-week periods, Belgian-compliant PDF invoices and email reminders before
storage ends.

- The full functional and technical specification is in [`CLAUDE.md`](CLAUDE.md).
- The user interface, emails and PDFs are in French; code and comments are in English.

## Status

| Milestone | Content | State |
|---|---|---|
| M0 | Scaffold: project, apps, `.env` config, French locale, login, base layout | Done |
| M1 | Settings & rows | To do |
| M2 | Clients & vehicles | To do |
| M3 | Booking engine | To do |
| M4 | Planning grid | To do |
| M5 | Invoicing | To do |
| M6 | Reminders | To do |
| M7 | Dashboard | To do |
| M8 | Deployment kit | To do |

## Requirements

- Python 3.12 or newer.
- The system libraries WeasyPrint needs to generate PDFs (Pango):
  - **Debian / Ubuntu:** `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`
  - **macOS (Homebrew):** `brew install pango`

  See the [WeasyPrint installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)
  if PDF generation fails.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then set DJANGO_DEBUG=True in .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and log in with the user you just created.

In development (`DJANGO_DEBUG=True`):

- `DJANGO_SECRET_KEY` may be left empty: a throwaway key is used.
- `DJANGO_ALLOWED_HOSTS` may be left empty: `localhost` and `127.0.0.1` are allowed.
- If `EMAIL_HOST` is empty, emails (for example "mot de passe oublié") are printed in the
  terminal running `runserver` instead of being sent.

## Tests and code style

```bash
pytest           # run the test suite
ruff check .     # lint
ruff format .    # format the code
```

Both `pytest` and `ruff check .` must pass before merging into `main`.

## Configuration (`.env`)

All settings that differ between machines, and every secret, live in a `.env` file at the
project root. It is never committed; `.env.example` lists every variable.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Long random string, mandatory in production. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `True` only on a development machine, never in production |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated domain names the site answers to |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated full origins, e.g. `https://stockage.example.be` |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | SMTP server used to send emails |
| `DJANGO_DB_PATH` | Optional: location of the SQLite file (default `db.sqlite3` in the project) |

## Project layout

```
config/       Django project: settings, URLs, French date formats (config/formats/)
core/         Shared code: dashboard, formatting helpers (money as "1 234,56 €")
clients/      Clients and vehicles (M2)
storage/      Rows, bookings, planning, fit and boxed-in logic (M1, M3, M4)
invoicing/    Invoices, credit notes, PDF generation (M5)
reminders/    Reminder emails and the send_reminders command (M6)
templates/    HTML templates (French), including the login pages in registration/
static/       Pico.css, HTMX and project CSS, vendored (no build step, no CDN)
tests/        pytest test suite
```

Business logic goes in `services.py` modules (for example `storage/services.py`), not in views
or templates, so it can be unit-tested.

### Notes for maintainers

- **Every page requires login.** This is enforced by Django's `LoginRequiredMiddleware`
  (see `config/settings.py`). A view that must be public needs the `@login_not_required`
  decorator; in V1 only the login and password-reset pages are public.
- **Users** are created with `python manage.py createsuperuser` or in the Django admin at
  `/admin/`.
- **Front-end libraries** are plain files in `static/`. To upgrade Pico.css or HTMX, download
  the new minified file and replace the old one.
- **SQLite** runs in WAL mode with a 5-second busy timeout; this is set in `config/settings.py`.

## Production

Deployment files and step-by-step instructions (gunicorn, Caddy, daily reminders, backups and
restore) arrive with milestone M8.
