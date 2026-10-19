# Backlog

Improvements requested after testing, with the decisions taken. Items are built only once
they are approved. The specification itself is `CLAUDE.md`; its section 15 lists the features
left out of V1 (Peppol, waitlist, GDPR tools…).

## To do

### V3-2 – Document status colours

*Bookings · display · small*

Make the document statuses (V3-1) readable at a glance, everywhere they appear: the
"Documents" block of a booking, the "ID" / "Ass." badges in the bookings list and the
"Documents à compléter" list on the dashboard.

- **Valide**: green.
- **Manquant**: orange (today it is grey).
- **Invalide**: stays red.

CSS only (`.doc-valid`, `.doc-missing`, `.doc-invalid` in `static/css/app.css`), keeping
enough contrast for the text in the badges.

## Done (V3)

### V3-1 – Document checks on each booking ✓

*Bookings · compliance · small to medium*

For every new booking, the admin checks the client's ID document and the vehicle's proof of
insurance for the booking period. Both checks are done again for every booking, even for a
returning client or vehicle (current paper process).

- Two statuses on each booking: **"Pièce d'identité"** and **"Assurance"**, each
  "manquant" (default), "valide" or "invalide", set by hand by the admin. Never copied from an
  earlier booking.
- Each change records who and when (e.g. "Valide – vérifié le 17/10/2026 par admin"), with an
  optional note to explain an "invalide" (wrong name, expired…).
- Booking detail: both badges, changed in one click.
- Bookings list: two small icons per booking and a "Documents à compléter" filter.
- Dashboard: a "Documents à compléter" list of the bookings starting soon or in stock where
  either status is not "valide".
- **No document is stored in the app**: the paper copies stay in the physical folder (an ID
  copy is sensitive personal data under GDPR, and backups go to a cloud folder).
- Technical: new fields on `Booking` (status, checked on, checked by, note, for each
  document) and a migration; existing bookings start as "manquant".

## Done (V2, pull request #2)

| # | Improvement |
|---|---|
| 1 | "+ Nouveau client" in the booking form: full client form inline; the new client is selected and the form goes straight on to "+ Nouveau véhicule" (full vehicle form). |
| 1b | Client address and phone required everywhere. Vehicle brand, model and height stay optional. |
| 2 | "Émettre" refused while the client's name, address or (business) VAT number is missing, with a link to the client form. |
| 3 | Price per vehicle length band: bands × price per band per period, a started band counts in full, no minimum; band size and price in Paramètres; full detail on the invoice line; price follows length corrections until the booking is invoiced. |
| – | A longer vehicle that no longer fits its row asks for confirmation ("Enregistrer quand même"). |
| 4 | Warehouse map: in the booking form; "Plan de l'entrepôt" (space management: a day or a date range, boxed-in vehicles and move plans, printable); "Trouver un emplacement" (placing a van: 5 best places and the map, opening the prefilled booking form). |
| – | Fix: the app stays in French whatever the browser's language. |

## Not planned yet

- Windows installation test (`install.ps1`) on a real PC, or on a GitHub Actions Windows runner.
- CI running `pytest` and `ruff` on every pull request.
- Tag `v0.1.0` once the Windows installation has been tested.
- Invoicing improvements mentioned during M6 ("will improve M5 and the invoicing
  methodology"): to be detailed.
