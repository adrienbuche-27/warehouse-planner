from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Case, Q, When
from django.db.models.functions import Lower

from core import validators


class ClientType(models.TextChoices):
    PRIVATE = "private", "Particulier"
    BUSINESS = "business", "Entreprise"


class Client(models.Model):
    """A customer storing one or more vehicles. Clients never log in.

    The address and phone are required: invoices need the address, and the phone is the
    usual way to reach the client about their vehicle. Invoices copy the client's name and
    address when they are issued, so editing a client never changes past invoices.
    """

    client_type = models.CharField(
        "type de client", max_length=10, choices=ClientType.choices, default=ClientType.PRIVATE
    )
    first_name = models.CharField("prénom", max_length=100, blank=True)
    last_name = models.CharField("nom", max_length=100, blank=True)
    company_name = models.CharField("nom de l'entreprise", max_length=200, blank=True)
    vat_number = models.CharField(
        "numéro de TVA",
        max_length=20,
        blank=True,
        validators=[validators.validate_vat_number],
        help_text="Obligatoire pour une entreprise. Ex. BE0123456789.",
    )
    street = models.CharField("rue et numéro", max_length=200)
    postal_code = models.CharField("code postal", max_length=10)
    city = models.CharField("localité", max_length=100)
    country = models.CharField("pays", max_length=100, default="Belgique")
    email = models.EmailField("email", help_text="Utilisé pour les rappels de fin de stockage.")
    phone = models.CharField("téléphone", max_length=50)
    notes = models.TextField("notes", blank=True)
    is_archived = models.BooleanField(
        "archivé",
        default=False,
        help_text="Un client archivé et ses véhicules sont masqués des listes et des réservations.",
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        # Sorted by the displayed name: company name for businesses, last name otherwise.
        ordering = [
            Lower(Case(When(client_type="business", then="company_name"), default="last_name")),
            Lower("first_name"),
        ]
        verbose_name = "client"
        verbose_name_plural = "clients"

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        self.vat_number = validators.normalize_vat_number(self.vat_number)
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.client_type == ClientType.PRIVATE:
            if not self.first_name.strip():
                errors["first_name"] = "Le prénom est obligatoire pour un particulier."
            if not self.last_name.strip():
                errors["last_name"] = "Le nom est obligatoire pour un particulier."
        elif self.client_type == ClientType.BUSINESS:
            if not self.company_name.strip():
                errors["company_name"] = "Le nom de l'entreprise est obligatoire."
            if not self.vat_number.strip():
                errors["vat_number"] = "Le numéro de TVA est obligatoire pour une entreprise."
        if errors:
            raise ValidationError(errors)

    @property
    def is_business(self) -> bool:
        return self.client_type == ClientType.BUSINESS

    @property
    def display_name(self) -> str:
        """Company name for a business, otherwise "Prénom Nom"."""
        if self.is_business and self.company_name:
            return self.company_name
        return self.contact_name

    @property
    def contact_name(self) -> str:
        """ "Prénom Nom" (for a business: the optional contact person)."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def address_lines(self) -> list[str]:
        """Postal address, one line per item (the country only when outside Belgium)."""
        lines = [self.street, f"{self.postal_code} {self.city}".strip()]
        if self.country and self.country.strip().lower() != "belgique":
            lines.append(self.country)
        return [line for line in lines if line]


class VehicleQuerySet(models.QuerySet):
    def active(self):
        """Vehicles that are neither archived themselves nor owned by an archived client."""
        return self.filter(is_archived=False, client__is_archived=False)

    def archived(self):
        return self.filter(Q(is_archived=True) | Q(client__is_archived=True))


def normalize_plate(value: str) -> str:
    """Plates are stored uppercase without spaces: " 1-abc 123 " -> "1-ABC123"."""
    return "".join((value or "").split()).upper()


class Vehicle(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="vehicles", verbose_name="client"
    )
    plate = models.CharField(
        "plaque",
        max_length=15,
        unique=True,
        error_messages={"unique": "Un véhicule avec cette plaque existe déjà."},
    )
    brand = models.CharField("marque", max_length=50, blank=True)
    model = models.CharField("modèle", max_length=50, blank=True)
    length_m = models.DecimalField(
        "longueur (m)",
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"), "La longueur doit être supérieure à 0."),
            MaxValueValidator(Decimal("20.00"), "Longueur trop grande : vérifiez la valeur."),
        ],
    )
    height_m = models.DecimalField(
        "hauteur (m)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"), "La hauteur doit être supérieure à 0.")],
        help_text="Facultatif, à titre d'information.",
    )
    notes = models.TextField("notes", blank=True)
    is_archived = models.BooleanField("archivé", default=False)

    objects = VehicleQuerySet.as_manager()

    class Meta:
        ordering = ["plate"]
        verbose_name = "véhicule"
        verbose_name_plural = "véhicules"

    def __str__(self):
        return self.plate

    def save(self, *args, **kwargs):
        self.plate = normalize_plate(self.plate)
        super().save(*args, **kwargs)

    @property
    def description(self) -> str:
        """E.g. "Fiat Ducato", or "" when unknown."""
        return f"{self.brand} {self.model}".strip()

    @property
    def is_effectively_archived(self) -> bool:
        return self.is_archived or self.client.is_archived
