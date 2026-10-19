# Gestion Stockage Camping-Cars

Internal web app to manage a camping-car storage warehouse in Belgium: clients and vehicles,
space planning in 2-week periods, Belgian-compliant PDF invoices and email reminders before
storage ends. It runs locally on a single Windows PC (no server, no domain) and is developed
on macOS.

The user interface, emails and PDFs are in French; code and comments are in English.

## Documentation

| Document | For whom | Content |
|---|---|---|
| This README | Whoever installs or develops the app | Requirements, local setup, configuration, production overview |
| [`docs/GUIDE-UTILISATEUR.md`](docs/GUIDE-UTILISATEUR.md) | The people using the app (French) | Every workflow step by step: booking, documents, invoicing, entry, end of storage, corrections, space management |
| [`docs/INSTALLATION-WINDOWS.md`](docs/INSTALLATION-WINDOWS.md) | The person installing the Windows PC (French) | Installation, updates, backups and restore |
| [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) | Maintainers | Project status and how each part of the code works |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Everyone | Improvements requested and decisions taken |
| [`CLAUDE.md`](CLAUDE.md) | Maintainers | The full functional and technical specification |

## Comment ça marche

L'application suit un stockage du premier contact à la sortie du véhicule. Les principaux
parcours, détaillés pas à pas dans le [guide d'utilisation](docs/GUIDE-UTILISATEUR.md) :

1. **Premiers réglages** (une seule fois) : dans **Paramètres**, la taille des rangées, le prix
   par tranche de 2 m, les informations de la société pour les factures, les textes des
   emails ; puis **Créer les rangées**.
2. **Prendre une réservation** : **Réservations → Trouver un emplacement** (date, durée,
   longueur du véhicule) propose les meilleures places et un plan de l'entrepôt ; **Réserver
   ici** ouvre la réservation pré-remplie, où l'on choisit ou crée le client et son véhicule.
   Le prix (par tranche de longueur) s'affiche tout de suite.
3. **Vérifier les documents** : sur chaque réservation, marquer la pièce d'identité et
   l'assurance « Valide », « Invalide » ou « Manquant » (les copies papier restent au dossier).
4. **Facturer** : **Créer la facture** fait un brouillon, **Émettre** lui donne son numéro et
   crée le PDF (qui ne change plus), **Envoyer par email**, puis **Marquer payée** à réception
   du paiement.
5. **Entrée du véhicule** : **Marquer en stock**, en suivant le plan de déplacement si des
   véhicules sont devant lui.
6. **Fin du stockage** : un rappel part tout seul au client et aux administrateurs 14 jours
   avant la fin ; ensuite **Prolonger** (et facturer les périodes ajoutées) ou **Marquer
   sortie**.
7. **Corriger** : une facture émise ne se modifie pas ; on fait une **note de crédit** puis une
   nouvelle facture.
8. **Gérer l'espace** : le **Planning** (occupation des rangées sur 6 mois) et le **Plan de
   l'entrepôt** (vue de dessus d'un jour ou d'une période, véhicules bloqués, impression).
9. **Chaque matin** : le **Tableau de bord** liste les sorties et entrées des 14 prochains jours,
   les documents à compléter, les factures impayées ou en retard et les rappels en échec.

Les rappels (08:00) et la sauvegarde des données (19:00) se font automatiquement chaque jour.

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
docs/         User guide, Windows installation guide (French), maintenance notes, backlog
tests/        pytest test suite
```

Business logic goes in `services.py` modules (for example `storage/services.py`), not in views
or templates, so it can be unit-tested. How each part works is described in
[`docs/MAINTENANCE.md`](docs/MAINTENANCE.md).

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
