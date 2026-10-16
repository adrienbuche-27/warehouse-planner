"""Fill the database with demo data: rows, clients, vehicles and bookings.

    python manage.py seed_demo            # empty database only
    python manage.py seed_demo --reset    # first delete all demo data, invoices included

Refuses to run when DEBUG is off (production) unless --force is given.
"""

import datetime
import random
import unicodedata
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.utils import timezone

from clients.models import Client, ClientType, Vehicle
from core.models import AppSettings
from invoicing.models import CreditNote, Invoice, NumberSequence
from storage import services
from storage.models import Booking, BookingStatus, Row

FIRST_NAMES = [
    "Jean", "Marie", "Luc", "Anne", "Paul", "Sophie", "Marc", "Julie", "Pierre", "Claire",
    "Michel", "Isabelle", "André", "Nathalie", "Philippe", "Christine", "Thierry", "Martine",
    "Didier", "Catherine", "Eric", "Véronique", "Patrick", "Sylvie", "Benoît", "Chantal",
]  # fmt: skip
LAST_NAMES = [
    "Dupont", "Lambert", "Martin", "Dubois", "Simon", "Laurent", "Lejeune", "Renard",
    "Leclercq", "Wouters", "Peeters", "Jacobs", "Mertens", "Collard", "Gillet", "Lemaire",
    "Hubert", "Thiry", "François", "Remacle", "Goffin", "Schmit", "Pirotte", "Lambotte",
]  # fmt: skip
COMPANIES = [
    "Camping Évasion SRL", "Ardennes Loisirs SRL", "Gaume Vacances SA", "Semois Location SRL",
    "Nomade Concept SRL", "Route & Liberté SA",
]  # fmt: skip
CITIES = [
    ("6700", "Arlon"), ("6600", "Bastogne"), ("6800", "Libramont"), ("6720", "Habay"),
    ("6760", "Virton"), ("6840", "Neufchâteau"), ("4000", "Liège"), ("5000", "Namur"),
]  # fmt: skip
VEHICLES = [
    ("Fiat", "Ducato"), ("Hymer", "B-Klasse"), ("Bürstner", "Lyseo"), ("Rapido", "Série 8"),
    ("Pilote", "Galaxy"), ("Chausson", "Titanium"), ("Adria", "Coral"), ("Dethleffs", "Pulse"),
    ("Carado", "T449"), ("Knaus", "Van TI"),
]  # fmt: skip


def _ascii(text: str) -> str:
    """ "Véronique" -> "veronique" (for demo email addresses)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


class Command(BaseCommand):
    help = "Crée des données de démonstration (jamais en production)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off.")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all rows, clients, vehicles, bookings and invoices first.",
        )

    def handle(self, *args, force=False, reset=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError(
                "DEBUG est désactivé : seed_demo ne doit jamais tourner en production. "
                "Utilisez --force si vous êtes vraiment sûr."
            )
        if (Client.objects.exists() or Row.objects.exists()) and not reset:
            raise CommandError(
                "La base contient déjà des données. Utilisez --reset pour les remplacer."
            )

        if reset and not settings.DEBUG and Invoice.objects.exclude(number=None).exists():
            raise CommandError(
                "Des factures émises existent : --reset les supprimerait. "
                "Refusé en production, même avec --force."
            )

        rng = random.Random(42)  # same demo data every time
        with transaction.atomic():
            if reset:
                self._delete_all()
            self._settings()
            services.create_rows(40)
            clients = self._clients(rng, 60)
            vehicles = self._vehicles(rng, clients, 80)
            created, boxed_in = self._bookings(rng, vehicles)

        self.stdout.write(
            self.style.SUCCESS(
                f"Données créées : 40 rangées, {len(clients)} clients, {len(vehicles)} véhicules, "
                f"{created} réservations dont {boxed_in} avec un blocage."
            )
        )

    def _delete_all(self):
        """Wipe the demo data. Issued invoices normally can never be deleted; this bypasses
        that protection on purpose, which is why it is refused in production (see handle)."""
        for model in (CreditNote, Invoice):
            for document in model.objects.exclude(pdf_file=""):
                document.pdf_file.delete(save=False)
            models.QuerySet.delete(model.objects.all())
        NumberSequence.objects.all().delete()
        Booking.objects.all().delete()
        Vehicle.objects.all().delete()
        Client.objects.all().delete()
        Row.objects.all().delete()

    def _settings(self):
        app_settings = AppSettings.load()
        if app_settings.price_per_period is None:
            app_settings.price_per_period = Decimal("45.00")
        demo_values = {
            "company_name": "Stockage Démo",
            "company_legal_form": "SRL",
            "company_address": "Rue de la Gare 1\n6700 Arlon",
            "company_vat_number": "BE0123456749",
            "company_bce_number": "0123456749",
            "company_rpm": "RPM Liège, division Arlon",
            "company_iban": "BE68539007547034",
            "company_bic": "GKCCBEBB",
            "company_email": "contact@stockage-demo.be",
            "company_phone": "063 12 34 56",
            "admin_notification_emails": "admin@stockage-demo.be",
        }
        # Only fill what is still empty: never overwrite real settings.
        for field, value in demo_values.items():
            if not getattr(app_settings, field):
                setattr(app_settings, field, value)
        app_settings.save()

    def _clients(self, rng, count):
        clients = []
        for i in range(count):
            postal_code, city = rng.choice(CITIES)
            common = {
                "street": f"Rue {rng.choice(['du Moulin', 'de la Station', 'Haute', 'des Prés'])} "
                f"{rng.randint(1, 120)}",
                "postal_code": postal_code,
                "city": city,
                "phone": f"04{rng.randint(70, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)} "
                f"{rng.randint(10, 99)}",
            }
            if i < len(COMPANIES):
                client = Client(
                    client_type=ClientType.BUSINESS,
                    company_name=COMPANIES[i],
                    vat_number=f"BE0{rng.randint(100000000, 999999999)}",
                    email=f"info{i}@example.be",
                    **common,
                )
            else:
                first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                client = Client(
                    first_name=first,
                    last_name=last,
                    email=f"{_ascii(first)}.{_ascii(last)}{i}@example.be",
                    **common,
                )
            client.save()
            clients.append(client)
        return clients

    def _vehicles(self, rng, clients, count):
        vehicles = []
        for i in range(count):
            # Every client gets one vehicle, the remaining ones go to random clients.
            owner = clients[i] if i < len(clients) else rng.choice(clients)
            brand, model = rng.choice(VEHICLES)
            vehicle = Vehicle.objects.create(
                client=owner,
                plate=f"{rng.randint(1, 2)}-{''.join(rng.choices('ABCDEFGHJKLMNPRSTVWXYZ', k=3))}"
                f"-{i:03d}",
                brand=brand,
                model=model,
                length_m=Decimal(
                    rng.choice(["5.40", "5.99", "6.40", "6.99", "7.20", "7.40", "7.99"])
                ),
                height_m=Decimal(rng.choice(["2.80", "2.90", "3.00", "3.10"])),
            )
            vehicles.append(vehicle)
        return vehicles

    def _bookings(self, rng, vehicles):
        """Place every vehicle with the suggestion engine, over the next 6 months.

        Mostly the best suggestion is taken; about one in eight takes the worst one on purpose,
        to create boxed-in situations to look at in the planning.
        """
        today = timezone.localdate()
        created = 0
        for vehicle in vehicles:
            start = today + datetime.timedelta(days=rng.randint(-60, 150))
            periods = rng.choice([1, 2, 3, 4, 6, 8, 12, 13])
            end = start + datetime.timedelta(days=periods * 14 - 1)
            suggestions = services.suggest_placements(vehicle, start, end)
            if not suggestions:
                continue
            if rng.random() < 0.125:
                choice = max(suggestions, key=lambda s: s.conflict_count)
            else:
                choice = suggestions[0]
            booking = Booking(
                vehicle=vehicle,
                row=choice.row,
                position=choice.position,
                start_date=start,
                periods=periods,
            )
            if end < today:
                booking.status = BookingStatus.ENDED
                booking.actual_check_in, booking.actual_check_out = start, end
            elif start <= today:
                booking.status = BookingStatus.STORED
                booking.actual_check_in = start
            booking.save()
            created += 1
        boxed_in = sum(1 for b in Booking.objects.active() if services.move_plans(b))
        return created, boxed_in
