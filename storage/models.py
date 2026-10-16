from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from core.models import AppSettings


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
