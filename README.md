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
| M1 | Settings & rows: Paramètres page, rows table with inline edit and bulk create | Done |
| M2 | Clients & vehicles: lists with live search, forms, archive, delete | Done |
| M3 | Booking engine: fit check, boxed-in detection, suggestions, booking screens | Done |
| M4 | Planning grid: rows × 2-week windows, cell details, free-space filter | Done |
| M5 | Invoicing: drafts, gap-free numbering, PDF, payments, credit notes, email | Done |
| M6 | Reminders: daily email command, client and admin notices, blocked-entry digest | Done |
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
python manage.py seed_demo      # optional: demo rows, clients, vehicles and bookings
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and log in with the user you just created.

In development (`DJANGO_DEBUG=True`):

- `DJANGO_SECRET_KEY` may be left empty: a throwaway key is used.
- `localhost` and `127.0.0.1` are always allowed, whatever `DJANGO_ALLOWED_HOSTS` contains.
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
clients/      Clients and vehicles, search (clients/services.py)
storage/      Rows, bookings, planning; rules in storage/services.py and storage/planning.py
invoicing/    Invoices, credit notes, numbering, PDF and email (invoicing/services.py)
reminders/    ReminderLog, send_reminders command (reminders/services.py)
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
- **Paramètres** (`/parametres/`) holds every business setting: row length, safety gap,
  price, VAT, company details printed on invoices, reminder texts. Nothing is hard-coded:
  code reads values with `AppSettings.load()`. Bookings and invoices copy the price and VAT
  when they are created, so changing a setting never alters existing ones.
- **Rows** are created on the Paramètres page ("Créer les rangées" numbers them after the
  existing ones: R01, R02, …) and edited inline in the table.
- **Clients and vehicles** can be archived instead of deleted. Archived ones are hidden from
  lists (tick "Inclure les archivés" to see them); a vehicle whose client is archived counts as
  archived too. Deleting is refused as soon as bookings or invoices are linked: those links are
  declared with `on_delete=PROTECT`, and `core.services.protected_objects()` reports them.
- **Bookings** (`storage/services.py`) follow CLAUDE.md section 6:
  - `check_fit()` refuses a booking that does not fit in its row on every day of its stay,
    a position already taken, or a vehicle booked twice at the same time;
  - `get_blockers()` / `move_plans()` list the vehicles to move first when a vehicle is
    boxed in (closest to the aisle first, put back in reverse order);
  - `suggest_placements()` ranks rows and positions: fewest blocking situations, then the
    tightest fit, then the row order.
  The booking keeps the price and VAT of the day it was created. "Prolonger" keeps that price.
- **Planning** (`/planning/`, logic in `storage/planning.py`) shows 13 windows of 2 weeks from
  the Monday of the current week. Each cell is the peak occupancy of the row in that window
  (green below 70 %, orange 70–95 %, red above 95 %) with ⚠ when a vehicle of the row is boxed
  in when entering or leaving. Click a cell for its vehicles, move plans and "Nouvelle
  réservation ici". "Espace libre min." keeps rows with that much free space in at least one
  window and dims the other windows.
- **Invoices** (`invoicing/services.py`) follow CLAUDE.md section 8, to be validated by the
  accountant before go-live:
  - "Créer la facture" on a booking makes a draft for its periods not invoiced yet (after
    "Prolonger", only the added periods: the complementary invoice). Drafts are editable and
    have no number. "+ Facture manuelle" makes a draft not linked to a booking.
  - "Émettre" assigns the number (`AAAA-NNNN`, gap-free per year), copies the client and company
    details, computes the totals (VAT per line), the structured communication and stores the PDF
    in `media/invoices/AAAA/`. Issuing is refused while the company name, address, VAT number
    or IBAN are missing in Paramètres. If anything fails, nothing is saved and no number is used.
  - Issued invoices and credit notes are read-only and can never be deleted (model, screens and
    admin). Only the payment fields can change: "Marquer payée" / "Annuler le paiement".
  - "Créer une note de crédit" copies all the lines of the invoice; edit them before issuing to
    credit only part of it. Credit notes are numbered `NC-AAAA-NNNN`. When the credit notes cover
    the whole invoice, the invoice becomes "Annulée".
  - The PDF layout and legal wording are in `templates/invoicing/invoice_pdf.html`; the email
    text is in `templates/invoicing/email_document.txt`.
- **Reminders** (`reminders/services.py`): `python manage.py send_reminders` must run once a
  day (08:00; the systemd timer comes with M8). For every active booking ending within
  "délai du rappel" days (Paramètres), it emails the client (editable text in Paramètres →
  Rappels) and the admins (with the move plan when the exit is blocked). It also sends the admins
  one digest per day when reservations starting in the next 14 days have a blocked entry.
  - Safe to run several times: a reminder already sent successfully is never sent again
    (`ReminderLog`). If the job did not run for a few days, the next run catches up.
  - Failures are logged with the error and retried on the next run; the history is shown on each
    booking page.
  - `--dry-run` shows what would be sent without sending; `--date AAAA-MM-JJ` acts as if today
    were that date (handy to check what the job will do).
- **Settings that shrink rows** (shorter default length or override, bigger gap) list the
  current and future bookings that would no longer fit and ask "Enregistrer quand même".
  A row with current or future bookings cannot be deactivated. Nothing is moved automatically.
- **`python manage.py seed_demo`** creates demo data (40 rows, 60 clients, 80 vehicles and
  their bookings, some of them boxed in) and fills the empty company details. It refuses to run
  when `DJANGO_DEBUG` is off, unless `--force`; `--reset` replaces all existing data, including
  invoices (always refused in production when issued invoices exist). Never run it in production.
- **Uploaded files** (the logo, later the invoice PDFs) are never served publicly: they go
  through views that require login (for example `/parametres/logo/`).
- **"Envoyer un email de test"** sends an email to the logged-in user (or to the admin emails)
  to check the SMTP settings in `.env`.
- **SQLite** runs in WAL mode with a 5-second busy timeout; this is set in `config/settings.py`.

## Production

Deployment files and step-by-step instructions (gunicorn, Caddy, daily reminders, backups and
restore) arrive with milestone M8.
