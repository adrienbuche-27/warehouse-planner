from django.db import models
from django.db.models import Q

from storage.models import Booking


class ReminderKind(models.TextChoices):
    CLIENT_END_NOTICE = "client_end_notice", "Rappel de fin au client"
    ADMIN_END_NOTICE = "admin_end_notice", "Rappel de fin aux administrateurs"
    ENTRY_DIGEST = "entry_digest", "Résumé des entrées bloquées"


class ReminderLog(models.Model):
    """One reminder email sent (or attempted) by `manage.py send_reminders`.

    A successful log is what prevents the same reminder from being sent twice: the
    constraints below allow only one successful client notice and one successful admin
    notice per booking, and one successful digest per day. Failed attempts are kept too
    (with the error) and the reminder is retried on the next run.
    """

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminders",
        verbose_name="réservation",
        help_text="Vide pour le résumé quotidien des entrées bloquées.",
    )
    kind = models.CharField("type", max_length=20, choices=ReminderKind.choices)
    digest_date = models.DateField("date du résumé", null=True, blank=True)
    sent_at = models.DateTimeField("envoyé le", auto_now_add=True)
    recipients = models.TextField("destinataires")
    success = models.BooleanField("réussi", default=False)
    error_message = models.TextField("erreur", blank=True)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "rappel envoyé"
        verbose_name_plural = "rappels envoyés"
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "kind"],
                condition=Q(success=True, booking__isnull=False),
                name="one_successful_reminder_per_booking_and_kind",
            ),
            models.UniqueConstraint(
                fields=["kind", "digest_date"],
                condition=Q(success=True, booking__isnull=True),
                name="one_successful_digest_per_day",
            ),
        ]

    def __str__(self):
        status = "envoyé" if self.success else "échec"
        return f"{self.get_kind_display()} – {self.booking or self.digest_date} ({status})"
