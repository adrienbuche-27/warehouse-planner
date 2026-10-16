# Gestion Stockage Camping-Cars

Internal web app to manage a camping-car storage warehouse in Belgium: clients and vehicles,
space planning in 2-week periods, Belgian-compliant PDF invoices and email reminders before
storage ends. It runs locally on a single Windows PC (no server, no domain) and is developed
on macOS.

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
| M7 | Dashboard: KPIs, next 14 days, forecast and revenue charts; reminders history page | Done |
| M8 | Local installation kit for Windows: install/update scripts, scheduled tasks, backup and restore | Done |

## Requirements

- Python 3.12 or newer.
- The system libraries WeasyPrint needs to generate PDFs (Pango):
  - **Debian / Ubuntu:** `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`
  - **macOS (Homebrew):** `brew install pango`
  - **Windows:** MSYS2 and `pacman -S mingw-w64-x86_64-pango`, see
    [`docs/INSTALLATION-WINDOWS.md`](docs/INSTALLATION-WINDOWS.md)

  See the [WeasyPrint installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)
  if PDF generation fails.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then set DJANGO_DEBUG=True in .env
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo      # optional demo data (about 20 s: it also issues invoices)
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
| `DJANGO_ALLOWED_HOSTS` | Host names the app answers to (default `localhost,127.0.0.1`) |
| `DJANGO_HTTPS` | `False` (local use over `http://localhost`); `True` only behind an HTTPS proxy |
| `APP_PORT` | Port of the Windows server, 8000 by default (`http://localhost:8000`) |
| `BACKUP_DIR`, `BACKUP_KEEP_DAYS` | Where `backup_data` writes its zips (ideally a synced cloud folder) and how many days to keep (30) |
| `WEASYPRINT_DLL_DIRECTORIES` | Windows only: folder of the Pango DLLs, `C:\msys64\mingw64\bin` |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | SMTP server used to send emails |
| `DJANGO_DB_PATH` | Optional: location of the SQLite file (default `db.sqlite3` in the project) |

## Project layout

```
config/       Django project: settings, URLs, French date formats (config/formats/)
core/         Settings, dashboard and charts, backup/restore, shared helpers ("1 234,56 €")
clients/      Clients and vehicles, search (clients/services.py)
storage/      Rows, bookings, planning; rules in storage/services.py and storage/planning.py
invoicing/    Invoices, credit notes, numbering, PDF and email (invoicing/services.py)
reminders/    ReminderLog, send_reminders command (reminders/services.py)
templates/    HTML templates (French), including the login pages in registration/
static/       Pico.css, HTMX and project CSS, vendored (no build step, no CDN)
deploy/windows/  install/update/uninstall scripts and the launchers of the scheduled tasks
docs/         INSTALLATION-WINDOWS.md (French installation guide)
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
- **Clients and vehicles**: a client's address and phone are required (invoices need the
  address). Both share one form template, `templates/clients/_client_fields.html`, also used by
  "+ Nouveau client" in the booking form: a client created there is selected and the booking
  goes straight on to "+ Nouveau véhicule". They can be archived instead of deleted. Archived ones are hidden from
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
    or IBAN are missing in Paramètres, or while the client's name, address or (for a business)
    VAT number are missing (`missing_client_details()`; the invoice page links to the client
    form, which comes back to the invoice). If anything fails, nothing is saved and no number
    is used.
  - Issued invoices and credit notes are read-only and can never be deleted (model, screens and
    admin). Only the payment fields can change: "Marquer payée" / "Annuler le paiement".
  - "Créer une note de crédit" copies all the lines of the invoice; edit them before issuing to
    credit only part of it. Credit notes are numbered `NC-AAAA-NNNN`. When the credit notes cover
    the whole invoice, the invoice becomes "Annulée".
  - The PDF layout and legal wording are in `templates/invoicing/invoice_pdf.html`; the email
    text is in `templates/invoicing/email_document.txt`.
- **Tableau de bord** (`core/dashboard.py`): today's occupancy and free metres, bookings in
  progress, unpaid and overdue invoices (net of partial credit notes), the end-of-storage dates
  and the entries of the next 14 days (with "reminder sent" and ⚠ when a vehicle is boxed in),
  failed reminders, and two charts: forecast occupancy for the next 12 two-week windows and
  monthly revenue excl. VAT (issued invoices minus credit notes) over 12 months. The charts are
  inline SVG computed on the server (`core/charts.py`); hover a bar for its value, or open
  "Voir les données" for the table.
- **Historique des rappels** (`/rappels/`, linked from the dashboard and the bookings list):
  every reminder email sent or attempted, with filters by type, result, date and plate/client.
- **Reminders** (`reminders/services.py`): `python manage.py send_reminders` must run once a
  day (08:00, Windows scheduled task). For every active booking ending within
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
  their bookings, some of them boxed in, past stays and their issued invoices) and fills the
  empty company details. It refuses to run
  when `DJANGO_DEBUG` is off, unless `--force`; `--reset` replaces all existing data, including
  invoices (always refused in production when issued invoices exist). Never run it in production.
- **Uploaded files** (the logo, later the invoice PDFs) are never served publicly: they go
  through views that require login (for example `/parametres/logo/`).
- **"Envoyer un email de test"** sends an email to the logged-in user (or to the admin emails)
  to check the SMTP settings in `.env`.
- **Backups**: `python manage.py backup_data` writes `sauvegarde-AAAAMMJJ-HHMMSS.zip` (a
  consistent copy of the database made with SQLite's online backup, plus `media/`) into
  `BACKUP_DIR`, keeping 30 days. `python manage.py restore_backup <zip>` restores one after
  saving the current data (`avant-restauration-….zip`). Stop the app before restoring.
- **SQLite** runs in WAL mode with a 5-second busy timeout; this is set in `config/settings.py`.

## Production: the Windows PC

The app runs on one Windows PC at the business, opened at `http://localhost:8000`. The
step-by-step guide, in French for the person installing it, is
[`docs/INSTALLATION-WINDOWS.md`](docs/INSTALLATION-WINDOWS.md). In short:

1. Install Python 3.12+ and MSYS2 + Pango (for the PDFs).
2. Copy the project to `C:\GestionStockage` (not in a synced folder).
3. Run `powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1`.

`install.ps1` creates the virtual environment, `.env` (generated secret key, backup folder),
the database, the first user, a desktop shortcut and three scheduled tasks:

| Task | When | What |
|---|---|---|
| Stockage - application | at logon | `deploy/windows/run_server.py`: waitress on `127.0.0.1:8000`, log in `logs/app.log` |
| Stockage - rappels | daily 08:00 | `run_task.py send_reminders`, log in `logs/send_reminders.log` |
| Stockage - sauvegarde | daily 19:00 | `run_task.py backup_data`, log in `logs/backup_data.log` |

All three run as soon as possible when their time was missed (PC off). They use `pythonw.exe`, so
no console window opens. `update.ps1` updates an installation (backup first), and
`uninstall.ps1` removes the tasks and the shortcut, keeping the data.

The Python parts (server launcher, task launcher, backup, restore) are covered by the tests.
**The PowerShell scripts cannot be tested from macOS or Linux: try a full installation on a
Windows PC before the first install at the client's.**
