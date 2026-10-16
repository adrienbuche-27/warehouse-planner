from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core import validators

DEFAULT_REMINDER_SUBJECT = "Fin de stockage de votre camping-car {plaque} le {date_fin}"

DEFAULT_REMINDER_BODY = """Bonjour {client_nom},

Nous vous informons que la période de stockage de votre camping-car immatriculé {plaque} \
se termine le {date_fin}.

Pourriez-vous nous confirmer le jour et l'heure auxquels vous souhaitez venir le récupérer ?

Si vous préférez prolonger le stockage, il vous suffit de nous contacter par téléphone au \
{societe_telephone} ou par email à {societe_email}.

Nous restons à votre disposition pour toute question.

Cordialement,
{societe_nom}
"""


class VatRegime(models.TextChoices):
    STANDARD = "standard", "Assujetti à la TVA (régime normal)"
    FRANCHISE = "franchise", "Franchise des petites entreprises (pas de TVA)"


class AppSettings(models.Model):
    """Application-wide settings, edited on the "Paramètres" page.

    Only one row exists (primary key 1). Always access it with `AppSettings.load()`.
    Bookings and invoices copy the values they need (price, VAT) when they are created,
    so changing a setting never alters existing bookings or invoices.
    """

    SINGLETON_PK = 1

    # Entrepôt
    default_row_length_m = models.DecimalField(
        "longueur de rangée par défaut (m)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("16.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Utilisée pour toutes les rangées sans longueur spécifique.",
    )
    vehicle_gap_m = models.DecimalField(
        "espace de sécurité entre véhicules (m)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    period_days = models.PositiveSmallIntegerField(
        "durée d'une période (jours)",
        default=14,
        validators=[MinValueValidator(1)],
        help_text="Durée d'une période de facturation. À laisser à 14 jours sauf raison précise.",
    )

    # Tarifs & TVA
    price_per_period = models.DecimalField(
        "prix par période (HTVA)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Prix hors TVA pour une période.",
    )
    vat_regime = models.CharField(
        "régime de TVA",
        max_length=10,
        choices=VatRegime.choices,
        default=VatRegime.STANDARD,
    )
    vat_rate = models.DecimalField(
        "taux de TVA (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Utilisé uniquement en régime normal.",
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        "délai de paiement (jours)",
        default=30,
        help_text="Date d'échéance = date de la facture + ce nombre de jours.",
    )

    # Société (mentions sur factures)
    company_name = models.CharField("dénomination", max_length=200, blank=True)
    company_legal_form = models.CharField(
        "forme juridique",
        max_length=50,
        blank=True,
        help_text="Ex. SRL. Laisser vide pour une personne physique.",
    )
    company_address = models.TextField("adresse du siège", blank=True)
    company_vat_number = models.CharField(
        "numéro de TVA",
        max_length=20,
        blank=True,
        validators=[validators.validate_vat_number],
        help_text="Ex. BE0123456789.",
    )
    company_bce_number = models.CharField(
        "numéro d'entreprise (BCE)",
        max_length=20,
        blank=True,
        validators=[validators.validate_bce_number],
        help_text="En général les mêmes chiffres que le numéro de TVA.",
    )
    company_rpm = models.CharField(
        "RPM",
        max_length=200,
        blank=True,
        help_text="Ex. RPM Liège, division Arlon (sociétés uniquement).",
    )
    company_iban = models.CharField(
        "IBAN", max_length=40, blank=True, validators=[validators.validate_iban]
    )
    company_bic = models.CharField(
        "BIC", max_length=11, blank=True, validators=[validators.validate_bic]
    )
    company_email = models.EmailField(
        "email",
        blank=True,
        help_text="Adresse d'expédition des emails envoyés aux clients.",
    )
    company_phone = models.CharField("téléphone", max_length=50, blank=True)
    company_logo = models.ImageField(
        "logo",
        upload_to="company/",
        blank=True,
        help_text="Facultatif, imprimé en haut à gauche des factures.",
    )

    # Rappels
    reminder_days_before_end = models.PositiveSmallIntegerField(
        "délai du rappel (jours avant la fin)",
        default=14,
    )
    admin_notification_emails = models.TextField(
        "emails des administrateurs",
        blank=True,
        validators=[validators.validate_email_list],
        help_text="Séparés par des virgules. Reçoivent les rappels internes.",
    )
    client_reminder_subject = models.CharField(
        "objet de l'email au client",
        max_length=200,
        default=DEFAULT_REMINDER_SUBJECT,
        validators=[validators.validate_reminder_template],
    )
    client_reminder_body = models.TextField(
        "texte de l'email au client",
        default=DEFAULT_REMINDER_BODY,
        validators=[validators.validate_reminder_template],
    )

    class Meta:
        verbose_name = "paramètres"
        verbose_name_plural = "paramètres"

    def __str__(self):
        return "Paramètres"

    def save(self, *args, **kwargs):
        # Whatever happens, there is only ever one row.
        self.pk = self.SINGLETON_PK
        self.company_vat_number = validators.normalize_vat_number(self.company_vat_number)
        self.company_bce_number = validators.normalize_bce_number(self.company_bce_number)
        self.company_iban = validators.normalize_iban(self.company_iban)
        self.company_bic = validators.normalize_bic(self.company_bic)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Les paramètres ne peuvent pas être supprimés.")

    @classmethod
    def load(cls) -> "AppSettings":
        """Return the settings, creating them with default values the first time."""
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj

    @property
    def admin_emails(self) -> list[str]:
        return validators.split_emails(self.admin_notification_emails)

    @property
    def sender_email(self) -> str:
        """Sender address for emails to clients: the company email, else DEFAULT_FROM_EMAIL."""
        return self.company_email or settings.DEFAULT_FROM_EMAIL
