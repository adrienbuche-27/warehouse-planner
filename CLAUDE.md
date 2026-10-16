# Gestion Stockage Camping-Cars

Internal web app to manage a camping-car storage warehouse: clients and vehicles, space planning in 2-week periods, Belgian-compliant PDF invoices, and email reminders before storage ends.

> **For Claude Code:** this file is the full specification (`README.md` is the short guide for users and maintainers). Implement it milestone by milestone (section 12), committing as described in section 13. When something here is ambiguous or conflicts with a technical constraint, stop and ask rather than guessing. Code, comments, commit messages and identifiers are in **English**; everything the user sees (UI, emails, PDFs) is in **French**.

---

## 1. Context

- Small business located in **Belgium**.
- About **100 vehicles** maximum, stored in a single warehouse.
- **2–3 internal users** (admins). Clients never log in.
- The app runs **locally on a single Windows PC** at the business (no server, no domain): it is
  opened at `http://localhost:8000` on that PC. Development happens on macOS.
- The app is a **tracker**: it does not take payments. It records whether an invoice was paid.
- Future maintainers are **not experienced developers**. Favour boring, well-documented, built-in solutions over clever ones. Minimise dependencies and avoid any frontend build step.

---

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | |
| Framework | Django 5.x | Admin, auth, ORM, migrations and forms built in |
| Database | SQLite (WAL mode) | Single file, no server; enough for this load |
| Interactivity | Django templates + HTMX | No JS framework, no build step |
| CSS | Pico.css (vendored in `static/`) | Clean defaults, no build step |
| PDF | WeasyPrint | HTML/CSS template → PDF |
| Email | Django SMTP backend | Any provider (own mailbox, Brevo, etc.) |
| Scheduled jobs | Django management command + Windows Task Scheduler | No Celery, no Redis |
| Config | `django-environ` + `.env` file | Secrets out of Git |
| Tests | `pytest` + `pytest-django` | |
| Lint/format | `ruff` | |
| Production server | `waitress` on 127.0.0.1, static files by WhiteNoise | Runs on Windows; local only, so no HTTPS |

Dependencies are pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (tests, ruff). Do not add other dependencies without asking.

---

## 3. Repository structure

```
.
├── README.md               # setup and maintenance guide
├── CLAUDE.md               # this specification
├── .env.example
├── .gitignore              # db.sqlite3, .env, media/, venv/, __pycache__/, backups/
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml          # ruff + pytest config
├── manage.py
├── config/                 # Django project (settings, urls, wsgi)
├── core/                   # AppSettings singleton, dashboard, shared utils
├── clients/                # Client, Vehicle
├── storage/                # Row, Booking, planning, fit & boxed-in logic
├── invoicing/              # Invoice, InvoiceLine, CreditNote, PDF generation
├── reminders/              # ReminderLog, send_reminders command, email templates
├── templates/              # base.html + per-app templates (French)
├── static/                 # pico.css, htmx.min.js, app.css, logo placeholder
├── deploy/windows/         # install.ps1, update.ps1, uninstall.ps1, run_server.py, run_task.py
├── docs/                   # INSTALLATION-WINDOWS.md (French, for the person installing)
└── tests/
```

Business logic lives in plain functions in `services.py` modules (for example `storage/services.py`), **not** in views or templates, so it can be unit-tested.

---

## 4. Localisation and conventions

- `LANGUAGE_CODE = "fr-be"`, `TIME_ZONE = "Europe/Brussels"`, `USE_TZ = True`.
- Dates displayed `dd/mm/yyyy`. Amounts displayed `1 234,56 €`.
- Money stored as `DecimalField(max_digits=10, decimal_places=2)`. Never use floats for money.
- Lengths stored in **metres** as `DecimalField(max_digits=5, decimal_places=2)`.
- All user-facing strings in French, written directly in templates (no translation framework needed).

---

## 5. Data model

### 5.1 `core.AppSettings` (singleton, editable on the "Paramètres" page)

Only one row may exist. Enforce this in `save()` and expose it through `AppSettings.load()`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `default_row_length_m` | Decimal | 16.00 | Used when a row has no override |
| `vehicle_gap_m` | Decimal | 0.50 | Safety gap between two vehicles in a row |
| `period_days` | Int | 14 | Length of a billing period. Keep at 14; exposed for clarity, not meant to change often |
| `price_per_period` | Decimal | — | Price **excluding VAT** for one period |
| `vat_regime` | Choice | `standard` | `standard` (VAT applies) or `franchise` (small-business exemption) |
| `vat_rate` | Decimal | 21.00 | Percentage, used when `vat_regime = standard` |
| `reminder_days_before_end` | Int | 14 | |
| `payment_terms_days` | Int | 30 | Due date = issue date + this |
| `company_name` | Char | | Legal name |
| `company_legal_form` | Char | | e.g. SRL, or blank for a natural person |
| `company_address` | Text | | |
| `company_vat_number` | Char | | `BE0123456789` |
| `company_bce_number` | Char | | Usually same digits as VAT number |
| `company_rpm` | Char | | e.g. "RPM Liège, division Arlon" (companies only) |
| `company_iban` | Char | | |
| `company_bic` | Char | | |
| `company_email` | Email | | Sender of client emails |
| `company_phone` | Char | | |
| `company_logo` | Image | blank | Optional, printed on invoices |
| `admin_notification_emails` | Text | | Comma-separated; receives admin reminders |
| `client_reminder_subject` / `client_reminder_body` | Char / Text | sensible French defaults | Template with placeholders, see 9.2 |

**Propagation rule:** every place that needs a length, gap, price, VAT rate or reminder delay reads it from `AppSettings` (or the row override). Nothing is hard-coded.

### 5.2 `clients.Client`

| Field | Type | Notes |
|---|---|---|
| `client_type` | Choice | `private` (particulier) / `business` (entreprise) |
| `first_name`, `last_name` | Char | Required for private |
| `company_name` | Char | Required for business |
| `vat_number` | Char | Required for business; validated format `BE` + 10 digits (accept other EU prefixes too) |
| `street`, `postal_code`, `city`, `country` | Char | Required (printed on invoices). Country default "Belgique" |
| `email` | Email | Required (reminders) |
| `phone` | Char | Required |
| `notes` | Text | |
| `created_at`, `updated_at` | DateTime | |

`display_name` property: company name or "Prénom Nom". Clients are fully editable; past invoices are unaffected because they snapshot client data (see 5.6).

### 5.3 `clients.Vehicle`

| Field | Type | Notes |
|---|---|---|
| `client` | FK Client | A client can own several vehicles |
| `plate` | Char | Unique, stored uppercase without spaces |
| `brand`, `model` | Char | |
| `length_m` | Decimal | Required, > 0 |
| `height_m` | Decimal | Optional (informative in V1) |
| `notes` | Text | |

### 5.4 `storage.Row`

A row is one strip across the warehouse width. Vehicles are parked one after another along it, and the row is **accessible from one side only** (the aisle).

| Field | Type | Notes |
|---|---|---|
| `code` | Char | Unique, e.g. "R01" |
| `display_order` | Int | Order on the planning grid |
| `length_override_m` | Decimal, nullable | If blank, use `AppSettings.default_row_length_m` |
| `is_active` | Bool | Inactive rows hidden from planning and suggestions |
| `notes` | Text | |

`effective_length` property returns the override or the default.

Provide a "Créer N rangées" action on the settings page to bulk-create rows R01…RNN.

### 5.5 `storage.Booking`

| Field | Type | Notes |
|---|---|---|
| `vehicle` | FK Vehicle | |
| `row` | FK Row | |
| `position` | PositiveInt | 1 = closest to the aisle (access side) |
| `start_date` | Date | Any day |
| `periods` | PositiveInt | Number of 2-week periods, ≥ 1 |
| `end_date` | Date | **Computed and stored**: `start_date + periods × period_days − 1 day` (inclusive) |
| `status` | Choice | `reserved` (réservée), `stored` (en stock), `ended` (terminée), `cancelled` (annulée) |
| `actual_check_in`, `actual_check_out` | Date, nullable | Set when status changes |
| `price_per_period` | Decimal | **Snapshot** of the setting at creation |
| `vat_regime`, `vat_rate` | | **Snapshot** at creation |
| `notes` | Text | |
| `created_at`, `updated_at` | | |

`total_excl_vat = periods × price_per_period`.

Only bookings with status `reserved` or `stored` count as **active** for occupancy, fit and boxed-in logic.

**Extension:** "Prolonger" adds N periods, recomputes `end_date`, re-runs the fit and boxed-in checks, and offers to create a complementary invoice for the added periods only.

### 5.6 `invoicing.Invoice`, `InvoiceLine`, `CreditNote`

**Invoice**

| Field | Notes |
|---|---|
| `number` | Null while draft; assigned at issue (see 8.2) |
| `status` | `draft` (brouillon), `issued` (émise), `paid` (payée), `cancelled` (annulée via note de crédit) |
| `issue_date`, `due_date` | Set at issue |
| `booking` | FK Booking, nullable (allows manual invoices) |
| `client` | FK Client (for linking) |
| Client snapshot | `client_name`, `client_address`, `client_vat_number`, `client_type`, all copied at issue |
| Company snapshot | All `company_*` fields copied at issue |
| `vat_regime`, `vat_rate` | Copied at issue |
| `total_excl_vat`, `total_vat`, `total_incl_vat` | Computed from lines, stored at issue |
| `structured_reference` | Belgian structured communication `+++123/4567/89012+++`, see 8.4 |
| `paid_on`, `payment_method`, `payment_note` | Payment tracking |
| `pdf_file` | Generated PDF, stored at issue and never regenerated |

**InvoiceLine**: `invoice`, `description`, `service_start`, `service_end`, `quantity` (periods), `unit_price_excl_vat`, `line_total_excl_vat`.

**CreditNote** (note de crédit): same structure as Invoice (own number sequence, own lines and snapshots), plus a FK to the corrected `Invoice` and a `reason`. Issuing a credit note for the full amount sets the invoice status to `cancelled`.

### 5.7 `reminders.ReminderLog`

`booking`, `kind` (`client_end_notice`, `admin_end_notice`), `sent_at`, `recipients`, `success`, `error_message`. Unique constraint on (`booking`, `kind`) for successful sends, so a reminder is never sent twice.

---

## 6. Core business rules (`storage/services.py`)

All of these must have unit tests (section 11).

### 6.1 Fit check

A booking `B` (row `R`, dates `[start, end]`) fits if, **on every day** of `[start, end]`, the active bookings in `R` present that day, including `B`, satisfy:

```
sum(vehicle lengths) + vehicle_gap_m × (number of vehicles − 1)  ≤  R.effective_length
```

Implement it as a sweep over the change dates (each start date and each end date + 1) inside the interval rather than looping over every day. Also enforce that **no two active bookings overlapping in time share the same position** in a row.

Function: `check_fit(row, vehicle, start, end, position, exclude_booking=None) -> FitResult` returning `ok`, the peak occupancy in metres, the free metres at the peak, and the conflicting bookings if any.

### 6.2 Boxed-in detection

Positions are counted from the aisle: a vehicle at position `p` can only leave or enter if no vehicle at a position `< p` is physically present at that moment.

- **Blocked exit:** booking `B` (position `p`) is blocked on its exit date `B.end_date` if there is an active booking `C` in the same row with `C.position < B.position`, `C.start_date ≤ B.end_date` and `C.end_date > B.end_date`.
- **Blocked entry:** booking `B` is blocked on its entry date `B.start_date` if there is an active booking `C` in the same row with `C.position < B.position`, `C.start_date < B.start_date` and `C.end_date ≥ B.start_date`.

Function: `get_blockers(booking, event="exit"|"entry") -> list[Booking]`, returned **sorted by position ascending** (closest to the aisle first). This order is the order in which vehicles must be taken out; they are put back in reverse order. The UI words this as a move plan, e.g.:

> Pour sortir **AB-123-CD** (position 3) le 12/03/2027 : déplacer d'abord **XY-987-ZZ** (pos. 1), puis **QR-456-ST** (pos. 2). Les replacer ensuite dans l'ordre inverse.

### 6.3 Placement suggestion

Function: `suggest_placements(vehicle, start, end) -> list[Suggestion]`, for every active row and every candidate position where `check_fit` passes. Each suggestion reports the number of vehicles it would block and be blocked by (entry and exit, both directions).

Sort order:
1. Fewest blocking conflicts.
2. Best length fit (least wasted metres at peak), to keep large gaps for 8 m vehicles.
3. Row `display_order`.

Guiding principle: vehicles leaving **later** should sit **deeper** (higher position); short stays go near the aisle.

### 6.4 Pricing

- At booking creation: copy `price_per_period`, `vat_regime`, `vat_rate` from `AppSettings` into the booking.
- Changing settings later never alters existing bookings or invoices. Show a notice on the settings page saying so.
- Rounding: compute per line, round VAT to 2 decimals with `ROUND_HALF_UP`.

### 6.5 Settings changes that affect existing data

- Lowering `default_row_length_m`, a row override, or raising `vehicle_gap_m`: before saving, re-run the fit check on all **future and current** active bookings. If any would no longer fit, show the list and require explicit confirmation ("Enregistrer quand même"). Never delete or move bookings automatically.
- Deactivating a row with future active bookings: refuse and list them.

---

## 7. Screens (all behind login, French UI)

Navigation bar: **Tableau de bord · Planning · Réservations · Clients · Véhicules · Factures · Paramètres**.

### 7.1 Tableau de bord (dashboard)

- KPI cards: occupancy today (% of total metres and number of vehicles), free metres, active bookings, unpaid issued invoices (count and amount), overdue invoices.
- **Fin de stockage dans les 14 prochains jours**: table with vehicle, client, row/position, end date, reminder sent (yes/no), boxed-in warning icon with link to the move plan.
- **Prochaines entrées**: bookings starting in the next 14 days, also with blocked-entry warnings.
- **Occupation prévue**: bar chart of occupancy % for the next 12 two-week windows. Inline SVG generated server-side, or Chart.js from CDN; no build step.
- **Chiffre d'affaires mensuel**: bar chart, sum of `total_excl_vat` of issued invoices per month over the last 12 months.

### 7.2 Planning

- Grid: rows (R01…) vertically, **2-week windows** horizontally, starting on the Monday of the current week. Show 13 windows (about 6 months), with buttons for previous, next and today.
- Each cell shows peak occupancy in that window as `13,5 / 16 m`, coloured green (< 70%), orange (70–95%), red (> 95%).
- A warning icon appears in a cell if any vehicle in that row has a blocked entry or exit within that window.
- Clicking a cell opens a panel (HTMX) listing vehicles in that row for that window, by position: plate, client, dates, status, boxed-in warnings and move plans. A "Nouvelle réservation ici" button prefills row and start date.
- Filter: show only rows with free space ≥ X m (useful when placing an 8 m vehicle).

### 7.3 Réservations

- List with filters: status, row, client, date range. Search by plate or client name.
- **Booking form**: select client, then vehicle (HTMX dependent dropdown; "+ Nouveau véhicule" inline), start date, number of periods. The end date and price (HT, TVA, TTC) are computed live. "Proposer un emplacement" shows the ranked suggestions from 6.3 (top 5); picking one fills row and position. Manual row/position entry is allowed, but `check_fit` must pass. Blocking conflicts show a warning with the move plan and require ticking "Je confirme".
- Booking detail: all info, status actions (Marquer en stock / Marquer sortie / Annuler / Prolonger), linked invoices, reminder history, blockers.

### 7.4 Clients and Véhicules

- Lists with search; create/edit/delete forms. Deleting a client or vehicle that has bookings or invoices is **refused**; offer archiving instead (`is_archived` flag on both models).
- Client detail: contact info, vehicles, bookings, invoices, outstanding balance.

### 7.5 Factures

- List with filters: status, client, period, overdue only. Totals for the filtered selection.
- From a booking: "Créer la facture" makes a draft with one line ("Stockage camping-car [plaque] – du [début] au [fin] – N période(s) de 14 jours"). Drafts are editable.
- "Émettre" assigns the number, snapshots data, generates and stores the PDF. After that the invoice is **read-only**.
- "Marquer payée" records date, method (virement, espèces, autre) and note. "Annuler le paiement" is allowed (it is a tracking field, not accounting).
- "Créer une note de crédit" (from an issued invoice).
- Download PDF; "Envoyer par email" sends the PDF to the client.
- **To-do (not V1):** Peppol / UBL export for business clients.

### 7.6 Paramètres

- Form for all `AppSettings` fields, grouped: Entrepôt · Tarifs & TVA · Société (mentions sur factures) · Rappels.
- Rows table: code, override length, active, notes; inline edit; bulk create.
- Warning dialog per 6.5.
- "Envoyer un email de test" button.

### 7.7 Django admin

Keep it enabled at `/admin/` as a fallback for superusers, with sensible `list_display` and `search_fields`. Normal use must not require it.

---

## 8. Invoicing rules (Belgium)

> These rules reflect common Belgian practice and must be **validated by the business's accountant** before go-live. Keep the wording of legal mentions in templates so it is easy to change.

### 8.1 Mandatory content on every invoice PDF

- The word **"Facture"**, the invoice number and the issue date.
- Supplier: legal name, legal form, address, VAT number (`BE0…`), BCE number, RPM (if a company).
- Client: name and address. **For business clients, their VAT number.**
- Description of the service and the **service period** (start–end dates).
- Quantity (number of periods), unit price excl. VAT, line total excl. VAT.
- VAT rate and VAT amount per rate, total excl. VAT, total VAT, total incl. VAT.
- If `vat_regime = franchise`: no VAT charged, and print the mention **"Régime particulier de franchise des petites entreprises"** (wording to confirm with the accountant).
- Payment terms: due date, IBAN/BIC, structured communication.

Credit notes carry the title **"Note de crédit"**, their own number, and the number and date of the invoice they correct.

### 8.2 Numbering

- Format `AAAA-NNNN` (e.g. `2027-0001`). Credit notes `NC-AAAA-NNNN`.
- **Sequential and gap-free** per year. Assign the number inside a database transaction at issue time, using a dedicated `NumberSequence(kind, year, last_value)` table with `select_for_update()`.
- Drafts have no number, so deleting a draft never creates a gap.
- Issued invoices and credit notes **cannot be deleted** (enforce in model, views and admin).

### 8.3 Immutability

After issue, the invoice and its lines are read-only. Snapshots (client, company, VAT) are used to render the PDF, which is stored once and served as is. Any correction goes through a credit note plus a new invoice.

### 8.4 Structured communication (communication structurée)

Generate a Belgian structured reference for each invoice: 10 digits derived from the invoice (e.g. year + sequence, zero-padded) plus a 2-digit check equal to the number mod 97 (use 97 if the remainder is 0). Format `+++XXX/XXXX/XXXXX+++`. Unit-test it.

### 8.5 PDF

- HTML template `invoicing/invoice_pdf.html` rendered by WeasyPrint, A4, clean professional layout, logo top-left, French formatting.
- Store as `media/invoices/AAAA/AAAA-NNNN.pdf`.

---

## 9. Reminders

### 9.1 Job

Management command `python manage.py send_reminders`, run **once a day** (Windows scheduled task, 08:00; a missed run starts as soon as the PC is on). It is **idempotent**, so it can safely run twice. It also accepts `--dry-run`.

For every active booking where `end_date − today ≤ reminder_days_before_end` and `end_date ≥ today`, with no successful `ReminderLog` for that kind:

1. **Client email** (`client_end_notice`) to the client's email.
2. **Admin email** (`admin_end_notice`) to `admin_notification_emails`, including the **move plan** if the exit is blocked (6.2).

If the job was down for a few days, it catches up: any booking now within the window that never got its reminder gets it.

Additionally, send admins a **single daily digest** if any booking starting in the next 14 days has a blocked entry. Skip the email when there is nothing to report.

### 9.2 Templates

Editable in Paramètres, with placeholders: `{client_nom}`, `{plaque}`, `{date_fin}`, `{rangee}`, `{societe_nom}`, `{societe_telephone}`, `{societe_email}`. Provide a sensible default French text, polite, asking the client to confirm pickup or contact the company to extend.

Send emails as plain text plus a simple HTML version. Log failures in `ReminderLog` and show them on the dashboard.

---

## 10. Authentication and security

- Django auth; every view requires login (`LoginRequiredMixin` or middleware). No public pages.
- All users are staff admins in V1. Create them with `createsuperuser` or in Django admin.
- French login page, "mot de passe oublié" via email.
- `DEBUG=False` in production, `ALLOWED_HOSTS` from `.env` (localhost by default).
- The server listens on `127.0.0.1` only: nothing travels over the network, so HTTPS and
  secure cookies are off (`DJANGO_HTTPS=False`). `DJANGO_HTTPS=True` exists for a future setup
  behind an HTTPS reverse proxy.
- Secrets only in `.env` (never committed). Provide `.env.example`:

```
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_HTTPS=False
APP_PORT=8000
BACKUP_DIR=C:\Users\...\OneDrive\Sauvegardes Stockage
WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=
```

---

## 11. Tests (required)

Use `pytest` + `pytest-django`, plus `factory_boy` or simple fixture helpers. Minimum coverage:

- **Fit check:** 2 × 8 m fits in 16 m with gap 0 but not with gap 0.5 (8 + 0.5 + 8 = 16.5 > 16); 3 × 5 m with gap 0.5 = 16.0 fits; non-overlapping dates don't conflict; occupancy changes mid-interval; same position overlap rejected; `exclude_booking` works on edit.
- **Boxed-in:** exit blocked and not blocked; entry blocked; blockers sorted by position; cancelled/ended bookings ignored.
- **Suggestions:** ranking prefers no conflicts, then tighter fit.
- **Dates/pricing:** `end_date` computation; snapshot unaffected by later settings change; VAT rounding; franchise regime gives 0 VAT and the mention.
- **Invoicing:** gap-free numbering (including year rollover); drafts have no number; issued invoice immutable and undeletable; credit note cancels invoice; structured communication check digits.
- **Reminders:** sent once only; catch-up behaviour; dry-run sends nothing; admin email contains the move plan when blocked.
- **Settings change:** shrinking a row reports affected bookings.

`pytest` and `ruff check .` must pass before each merge.

---

## 12. Milestones

Each milestone ends with: tests passing, ruff clean, README updated if behaviour changed, merged into `main`.

| # | Milestone | Content | Done when |
|---|---|---|---|
| M0 | Scaffold | Django project, apps, settings via `.env`, French locale, base template with nav, login, Pico.css, HTMX, ruff, pytest, `.gitignore` | `runserver` shows the login page and an empty dashboard |
| M1 | Settings & rows | `AppSettings` singleton + Paramètres page, `Row` model + bulk create | Settings editable, rows created |
| M2 | Clients & vehicles | Models, CRUD, search, archive | Can manage clients and vehicles |
| M3 | Booking engine | `Booking` model, fit check, boxed-in, suggestions, booking form & detail, status actions, extension, tests | All section 6 tests pass |
| M4 | Planning grid | Grid, cell panel, filters, warnings | Visual check with seed data |
| M5 | Invoicing | Drafts, issue, numbering, PDF, payment tracking, credit notes, email PDF, tests | Sample PDF contains all section 8.1 mentions |
| M6 | Reminders | Command, templates, logs, digest, tests | Dry-run and real run behave correctly |
| M7 | Dashboard | KPIs, lists, charts | Dashboard reflects seed data |
| M8 | Local installation kit (Windows) | `deploy/windows/` scripts, backup and restore commands, installation guide (section 14) | A fresh Windows PC is set up from the guide |

Also provide `python manage.py seed_demo`, which creates about 40 rows, 60 clients, 80 vehicles (mix of 5–8 m) and bookings spread over the next 6 months, including some boxed-in situations. **Never run it in production** (refuse if `DEBUG=False` unless `--force`).

---

## 13. Git workflow

- Default branch `main`, always deployable.
- One branch per milestone: `feat/m3-booking-engine`, fixes as `fix/…`.
- Small, focused commits using **Conventional Commits**: `feat(storage): add fit check sweep`, `test(invoicing): gap-free numbering`, `fix(reminders): …`, `docs: …`, `chore: …`.
- Merge to `main` only when tests and ruff pass. Tag releases `v0.1.0` (after M8), etc.
- Never commit: `.env`, `db.sqlite3`, `media/`, `backups/`, `logs/`, virtualenvs.
- Migrations are committed. Do not edit migrations that already exist on `main`; create new ones.

---

## 14. Running

### Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set DJANGO_DEBUG=True locally
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo      # optional demo data
python manage.py runserver
pytest
```

WeasyPrint needs system libraries (Pango). Document the install commands for Debian/Ubuntu and macOS (Homebrew).

### Production (a single Windows PC, local only)

Provide in `deploy/windows/` and document step by step, in French, for a non-expert
(`docs/INSTALLATION-WINDOWS.md`):

- Prerequisites: Python 3.12+ from python.org; MSYS2 + `mingw-w64-x86_64-pango` for WeasyPrint
  (`WEASYPRINT_DLL_DIRECTORIES` in `.env`). The project folder must **not** be in a synced folder.
- `install.ps1`: venv, dependencies, `.env` with a generated secret key, `migrate`,
  `collectstatic`, first user, three scheduled tasks (application at logon, reminders daily
  08:00, backup daily 19:00, all "run as soon as possible if missed"), desktop shortcut.
  Safe to run again.
- `run_server.py` (waitress on `127.0.0.1:APP_PORT`) and `run_task.py` (management command →
  `logs/<command>.log`), started with `pythonw.exe` so no console window opens.
- `manage.py backup_data`: zip of a consistent SQLite copy (online backup API) + `media/`, into
  `BACKUP_DIR` (ideally a synced cloud folder); keep 30 days. `manage.py restore_backup <zip>`
  makes a safety copy first. **Document how to restore**, including on a new PC.
- SQLite pragmas set on connection: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`.
- Update procedure (`update.ps1`): backup, stop the app, `git pull` (or copy a new version),
  `pip install -r requirements.txt`, `migrate`, `collectstatic`, restart.

---

## 15. Out of scope for V1 (to-do list)

1. **Peppol / UBL e-invoicing** for business clients (B2B e-invoicing mandatory in Belgium since 1 Jan 2026). V1 marks business clients and stores their VAT number so this can be added as an export later.
2. Waitlist when the warehouse is full, with notification when space frees up.
3. Client access requests (pickup / visit dates).
4. GDPR tools: data export, deletion/anonymisation, retention policy (invoices must be kept for the legal period, so anonymise rather than delete).
5. Vehicle photos at check-in / check-out.
6. Overdue invoice reminders to clients.
7. Change history / audit log on bookings and invoices.
8. Hosting on a server (VPS with gunicorn, Caddy and HTTPS) or access from several computers.
