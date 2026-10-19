# Maintenance guide

For the people who maintain the code. How to install and run the app is in the
[README](../README.md); how to use it, in French, in [GUIDE-UTILISATEUR.md](GUIDE-UTILISATEUR.md).
The full specification is [`CLAUDE.md`](../CLAUDE.md) and the requested improvements are in
[BACKLOG.md](BACKLOG.md).

## Status

| Version | Content | State |
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
| V2 | After the first tests: client and vehicle created from the booking form, address and phone required, invoice refused without the client's address, price per length band, warehouse map, "Plan de l'entrepôt", "Trouver un emplacement" | Done |
| V3-1 | ID and insurance checked on each booking (status only, no file stored) | Done |

What is planned next is in [BACKLOG.md](BACKLOG.md). Not done yet: a test of the PowerShell
installation scripts on a real Windows PC, and the `v0.1.0` tag that should follow it.

## Notes for maintainers

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
  address). The Clients page and "+ Nouveau client" in the booking form share one form template,
  `templates/clients/_client_fields.html`; a client created from the booking form is selected
  and the booking goes straight on to "+ Nouveau véhicule". Clients and vehicles can be archived
  instead of deleted. Archived ones are hidden from lists (tick "Inclure les archivés" to see
  them); a vehicle whose client is archived counts as archived too. Deleting is refused as soon as bookings or invoices are linked: those links are
  declared with `on_delete=PROTECT`, and `core.services.protected_objects()` reports them.
- **Bookings** (`storage/services.py`) follow CLAUDE.md section 6:
  - `check_fit()` refuses a booking that does not fit in its row on every day of its stay,
    a position already taken, or a vehicle booked twice at the same time;
  - `get_blockers()` / `move_plans()` list the vehicles to move first when a vehicle is
    boxed in (closest to the aisle first, put back in reverse order);
  - `suggest_placements()` ranks rows and positions: fewest blocking situations, then the
    tightest fit, then the row order.
  Pricing is per length band (`core/pricing.py`): price per period = bands × price per band,
  a started band counting in full (7,40 m with 2 m bands = 4 bands). The booking keeps the band
  size, band price and VAT of the day it was created. The number of bands follows the vehicle
  length until the booking is invoiced: `storage.services.refresh_price()` runs when a vehicle
  length or a booking's vehicle is changed, and before the first invoice of a booking. Once
  invoiced, the price stays (correct with a credit note and a new invoice). "Prolonger" keeps
  the price. Bookings made before pricing per band keep their flat price.
- **Document checks** (backlog V3-1): every booking has an ID and an insurance status
  (`Booking.id_status`, `insurance_status`: manquant / valide / invalide), set by hand on the
  booking page with `storage.services.set_document_status()`, which records who, when and an
  optional note. Each booking is checked again, nothing is copied from an earlier one, and no
  file is stored (paper copies stay in the physical folder). The bookings list filters them
  (`?documents=a-completer`) and the dashboard lists those in stock or starting soon.
- **Planning** (`/planning/`, logic in `storage/planning.py`) shows 13 windows of 2 weeks from
  the Monday of the current week. Each cell is the peak occupancy of the row in that window
  (green below 70 %, orange 70–95 %, red above 95 %) with ⚠ when a vehicle of the row is boxed
  in when entering or leaving. Click a cell for its vehicles, move plans and "Nouvelle
  réservation ici". "Espace libre min." keeps rows with that much free space in at least one
  window and dims the other windows.
- **Warehouse map** (`storage/warehouse_map.py`): one strip per row, aisle on the left, each
  vehicle sized to its length by position (vehicles using a position one after another are
  stacked; free metres at the busiest moment). It is used by three screens, kept separate:
  - **"Plan de l'entrepôt"** (Planning › Plan de l'entrepôt, `storage:planning_map`), space
    management: one day or "du … au …" (one year at most). Vehicles boxed in when entering or
    leaving during those dates get ⚠ and each row lists the move plans. Click a vehicle for its
    booking, a row's free space to book there. "Imprimer" prints the map (CSS `@media print`).
  - **"Trouver un emplacement"** (Réservations › Trouver un emplacement,
    `storage:booking_find`), placing one van before booking it: start date, periods, and a
    length or a registered vehicle. It lists the 5 best places ("Réserver ici"), then the map
    with ✓ / ★ / ⚠ / ✗ per row. Both open the booking form prefilled
    (`?rangee=&position=&debut=&periodes=&vehicule=`). A van known only by its length is an
    unsaved `Vehicle` (`warehouse_map.planned_vehicle`).
  - **The booking form** shows the map for the stay being booked; clicking a row fills
    "Rangée" and "Position" with the best place in it (the fit check still applies on save).
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
