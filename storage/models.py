import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from clients.models import Vehicle
from core.models import AppSettings, VatRegime
from core.pricing import Totals, band_count, compute_totals


class Row(models.Model):
    """One strip across the warehouse width. Vehicles park one after another along it.

    The row is reachable from one side only (the aisle): position 1 is closest to the aisle.
    """

    code = models.CharField(
        "code",
        max_length=10,
        unique=True,
        help_text="Ex. R01.",
        error_messages={"unique": "Une rangée avec ce code existe déjà."},
    )
    display_order = models.PositiveIntegerField(
        "ordre d'affichage", default=0, help_text="Ordre sur le planning."
    )
    length_override_m = models.DecimalField(
        "longueur spécifique (m)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Laisser vide pour utiliser la longueur par défaut des paramètres.",
    )
    is_active = models.BooleanField(
        "active",
        default=True,
        help_text="Les rangées inactives sont masquées du planning et des suggestions.",
    )
    notes = models.TextField("notes", blank=True)

    class Meta:
        ordering = ["display_order", "code"]
        verbose_name = "rangée"
        verbose_name_plural = "rangées"

    def __str__(self):
        return self.code

    @property
    def effective_length(self) -> Decimal:
        """Length of this row: its own override, or the default length from the settings."""
        return self.effective_length_for(AppSettings.load())

    def effective_length_for(self, app_settings: AppSettings) -> Decimal:
        """Same as `effective_length`, with settings already loaded (avoids one query per row)."""
        if self.length_override_m is not None:
            return self.length_override_m
        return app_settings.default_row_length_m


class BookingStatus(models.TextChoices):
    RESERVED = "reserved", "Réservée"
    STORED = "stored", "En stock"
    ENDED = "ended", "Terminée"
    CANCELLED = "cancelled", "Annulée"


# Only these bookings take up space (occupancy, fit check, boxed-in detection).
ACTIVE_STATUSES = [BookingStatus.RESERVED, BookingStatus.STORED]


class DocumentStatus(models.TextChoices):
    """Result of the check of a document, done by hand by an admin for every booking."""

    MISSING = "missing", "Manquant"
    VALID = "valid", "Valide"
    INVALID = "invalid", "Invalide"


# Documents checked for every booking, even for a returning client or vehicle: the client's
# ID and the proof of insurance for the booking period. Only the result of the check is kept
# in the app; the paper copies stay in the physical folder (no file is stored).
# URL name -> (field prefix on Booking, label).
DOCUMENTS = {
    "identite": ("id", "Pièce d'identité"),
    "assurance": ("insurance", "Assurance"),
}


@dataclass(frozen=True)
class DocumentCheck:
    """One document of a booking, as shown on the screens."""

    slug: str  # "identite" or "assurance", used in URLs
    label: str
    status: str
    status_label: str
    checked_at: datetime.datetime | None
    checked_by: object  # a User, or None
    note: str

    @property
    def is_valid(self) -> bool:
        return self.status == DocumentStatus.VALID


def compute_end_date(start_date: datetime.date, periods: int, period_days: int) -> datetime.date:
    """Last day of storage, inclusive: start + periods × period_days − 1 day.

    Example: 1 period of 14 days from Monday 1 March ends on Sunday 14 March.
    """
    return start_date + datetime.timedelta(days=periods * period_days - 1)


class BookingQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=ACTIVE_STATUSES)

    def overlapping(self, start: datetime.date, end: datetime.date):
        """Bookings present on at least one day of [start, end] (both inclusive)."""
        return self.filter(start_date__lte=end, end_date__gte=start)

    def documents_incomplete(self):
        """Bookings where the ID or the insurance is not checked as valid yet."""
        return self.exclude(id_status=DocumentStatus.VALID, insurance_status=DocumentStatus.VALID)


class Booking(models.Model):
    """A vehicle stored at a position in a row for a number of 2-week periods.

    Position 1 is closest to the aisle. The band size, price per band and VAT are copied from
    the settings when the booking is created, so later changes to the settings never alter it.
    The number of bands follows the vehicle length: `storage.services.refresh_price()`
    recalculates it while the booking is not invoiced yet.

    Bookings created before pricing per band have no band fields: they keep their flat
    `price_per_period`.
    """

    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.PROTECT, related_name="bookings", verbose_name="véhicule"
    )
    row = models.ForeignKey(
        Row, on_delete=models.PROTECT, related_name="bookings", verbose_name="rangée"
    )
    position = models.PositiveSmallIntegerField(
        "position",
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="1 = le plus proche de l'allée.",
    )
    start_date = models.DateField("date d'entrée")
    periods = models.PositiveSmallIntegerField(
        "nombre de périodes", validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    end_date = models.DateField("date de fin", editable=False)
    status = models.CharField(
        "statut", max_length=10, choices=BookingStatus.choices, default=BookingStatus.RESERVED
    )
    actual_check_in = models.DateField("entrée effective", null=True, blank=True)
    actual_check_out = models.DateField("sortie effective", null=True, blank=True)
    # Price: band_count × price_per_band = price_per_period (all stored, see compute_price).
    band_length_m = models.DecimalField(
        "taille d'une tranche (m)", max_digits=5, decimal_places=2, null=True, editable=False
    )
    price_per_band = models.DecimalField(
        "prix par tranche (HTVA)", max_digits=10, decimal_places=2, null=True, editable=False
    )
    billed_length_m = models.DecimalField(
        "longueur facturée (m)", max_digits=5, decimal_places=2, null=True, editable=False
    )
    band_count = models.PositiveSmallIntegerField("nombre de tranches", null=True, editable=False)
    price_per_period = models.DecimalField(
        "prix par période (HTVA)", max_digits=10, decimal_places=2, editable=False
    )
    vat_regime = models.CharField(
        "régime de TVA", max_length=10, choices=VatRegime.choices, editable=False
    )
    vat_rate = models.DecimalField(
        "taux de TVA (%)", max_digits=5, decimal_places=2, editable=False
    )
    notes = models.TextField("notes", blank=True)
    # Document checks (see DOCUMENTS): the result, when and by whom, and an optional note
    # (e.g. why a document is "invalide").
    id_status = models.CharField(
        "pièce d'identité",
        max_length=10,
        choices=DocumentStatus.choices,
        default=DocumentStatus.MISSING,
    )
    id_checked_at = models.DateTimeField("pièce d'identité vérifiée le", null=True, blank=True)
    id_checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="pièce d'identité vérifiée par",
    )
    id_note = models.CharField("remarque sur la pièce d'identité", max_length=200, blank=True)
    insurance_status = models.CharField(
        "assurance",
        max_length=10,
        choices=DocumentStatus.choices,
        default=DocumentStatus.MISSING,
    )
    insurance_checked_at = models.DateTimeField("assurance vérifiée le", null=True, blank=True)
    insurance_checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="assurance vérifiée par",
    )
    insurance_note = models.CharField("remarque sur l'assurance", max_length=200, blank=True)
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["start_date", "row__display_order", "position"]
        verbose_name = "réservation"
        verbose_name_plural = "réservations"

    def __str__(self):
        return f"{self.vehicle.plate} – {self.row.code} pos. {self.position}"

    def save(self, *args, **kwargs):
        app_settings = AppSettings.load()
        if self.price_per_period is None:
            self.copy_prices_from(app_settings)
        self.end_date = compute_end_date(self.start_date, self.periods, app_settings.period_days)
        super().save(*args, **kwargs)

    def copy_prices_from(self, app_settings: AppSettings) -> None:
        """Snapshot of the current band size, price per band and VAT (done once, at creation)."""
        if app_settings.price_per_band is None:
            raise ValidationError(
                "Le prix par tranche n'est pas défini : renseignez-le dans les Paramètres."
            )
        self.band_length_m = app_settings.band_length_m
        self.price_per_band = app_settings.price_per_band
        self.vat_regime = app_settings.vat_regime
        self.vat_rate = app_settings.vat_rate
        self.compute_price()

    @property
    def priced_per_band(self) -> bool:
        """False for bookings created before pricing per band (flat price per period)."""
        return self.band_length_m is not None and self.price_per_band is not None

    def compute_price(self) -> None:
        """Bands of the vehicle's current length and the resulting price per period.

        Only sets the fields; `storage.services.refresh_price()` decides when to save them.
        """
        if not self.priced_per_band:
            return
        self.billed_length_m = self.vehicle.length_m
        self.band_count = band_count(self.billed_length_m, self.band_length_m)
        self.price_per_period = self.band_count * self.price_per_band

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def document(self, slug: str) -> DocumentCheck:
        prefix, label = DOCUMENTS[slug]
        status = getattr(self, f"{prefix}_status")
        return DocumentCheck(
            slug=slug,
            label=label,
            status=status,
            status_label=DocumentStatus(status).label,
            checked_at=getattr(self, f"{prefix}_checked_at"),
            checked_by=getattr(self, f"{prefix}_checked_by"),
            note=getattr(self, f"{prefix}_note"),
        )

    @property
    def documents(self) -> list[DocumentCheck]:
        """The ID and insurance checks, in display order."""
        return [self.document(slug) for slug in DOCUMENTS]

    @property
    def documents_complete(self) -> bool:
        return all(document.is_valid for document in self.documents)

    @property
    def totals(self) -> Totals:
        """Price of the whole booking: HT, TVA and TTC."""
        return compute_totals(self.periods, self.price_per_period, self.vat_regime, self.vat_rate)

    @property
    def total_excl_vat(self):
        return self.totals.excl_vat
