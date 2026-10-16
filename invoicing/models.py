"""Invoices and credit notes (CLAUDE.md, sections 5.6 and 8).

A document is a draft until it is issued. Issuing assigns its number, copies the client and
company details ("snapshots"), stores the totals and generates the PDF once. After that the
document and its lines are read-only and can never be deleted: corrections go through a
credit note (note de crédit) and, if needed, a new invoice.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from clients.models import Client, ClientType
from core.models import VatRegime
from core.pricing import round_money
from storage.models import Booking


class NumberSequence(models.Model):
    """Last number used per document kind and year, for gap-free numbering."""

    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    KIND_CHOICES = [(INVOICE, "Facture"), (CREDIT_NOTE, "Note de crédit")]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "year"], name="unique_sequence_per_year")
        ]
        verbose_name = "séquence de numérotation"
        verbose_name_plural = "séquences de numérotation"

    def __str__(self):
        return f"{self.get_kind_display()} {self.year} : {self.last_value}"


class IssuedDocumentError(ValidationError):
    """Raised when something tries to change or delete an issued invoice or credit note."""


class DocumentQuerySet(models.QuerySet):
    def delete(self):
        if self.exclude(number=None).exists():
            raise IssuedDocumentError("Un document émis ne peut jamais être supprimé.")
        return super().delete()


class BillingDocument(models.Model):
    """Fields shared by invoices and credit notes."""

    # Fields that may still change after issue (everything else is frozen).
    MUTABLE_AFTER_ISSUE = {"status", "updated_at", "emailed_at"}

    number = models.CharField("numéro", max_length=20, unique=True, null=True, blank=True)
    issue_date = models.DateField("date d'émission", null=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name="client")

    # Client snapshot (copied at issue)
    client_name = models.CharField("nom du client", max_length=200, blank=True)
    client_address = models.TextField("adresse du client", blank=True)
    client_vat_number = models.CharField("TVA du client", max_length=20, blank=True)
    client_type = models.CharField(max_length=10, choices=ClientType.choices, blank=True)

    # Company snapshot (copied at issue)
    company_name = models.CharField(max_length=200, blank=True)
    company_legal_form = models.CharField(max_length=50, blank=True)
    company_address = models.TextField(blank=True)
    company_vat_number = models.CharField(max_length=20, blank=True)
    company_bce_number = models.CharField(max_length=20, blank=True)
    company_rpm = models.CharField(max_length=200, blank=True)
    company_iban = models.CharField(max_length=40, blank=True)
    company_bic = models.CharField(max_length=11, blank=True)
    company_email = models.EmailField(blank=True)
    company_phone = models.CharField(max_length=50, blank=True)

    vat_regime = models.CharField("régime de TVA", max_length=10, choices=VatRegime.choices)
    vat_rate = models.DecimalField("taux de TVA (%)", max_digits=5, decimal_places=2)

    total_excl_vat = models.DecimalField("total HTVA", max_digits=10, decimal_places=2, default=0)
    total_vat = models.DecimalField("total TVA", max_digits=10, decimal_places=2, default=0)
    total_incl_vat = models.DecimalField("total TVAC", max_digits=10, decimal_places=2, default=0)

    pdf_file = models.FileField("PDF", upload_to="invoices/", blank=True)
    emailed_at = models.DateTimeField("envoyé par email le", null=True, blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        abstract = True

    def __str__(self):
        return self.number or f"Brouillon n° {self.pk}"

    def save(self, *args, **kwargs):
        if self.pk:
            self._refuse_changes_after_issue()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.number:
            raise IssuedDocumentError("Un document émis ne peut jamais être supprimé.")
        return super().delete(*args, **kwargs)

    def _refuse_changes_after_issue(self):
        saved = type(self).objects.filter(pk=self.pk).first()
        if saved is None or saved.number is None:
            return  # still a draft: anything may change
        changed = [
            field.name
            for field in self._meta.concrete_fields
            if field.name not in self.MUTABLE_AFTER_ISSUE
            and getattr(saved, field.attname) != getattr(self, field.attname)
            # The PDF is written once, right after the number is assigned.
            and not (field.name == "pdf_file" and not saved.pdf_file)
        ]
        if changed:
            raise IssuedDocumentError(
                f"Document émis : modification interdite ({', '.join(changed)})."
            )

    @property
    def is_draft(self) -> bool:
        return self.number is None

    @property
    def client_is_business(self) -> bool:
        return self.client_type == ClientType.BUSINESS

    @property
    def is_franchise(self) -> bool:
        return self.vat_regime == VatRegime.FRANCHISE


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Brouillon"
    ISSUED = "issued", "Émise"
    PAID = "paid", "Payée"
    CANCELLED = "cancelled", "Annulée (note de crédit)"


class PaymentMethod(models.TextChoices):
    TRANSFER = "transfer", "Virement"
    CASH = "cash", "Espèces"
    OTHER = "other", "Autre"


class Invoice(BillingDocument):
    MUTABLE_AFTER_ISSUE = BillingDocument.MUTABLE_AFTER_ISSUE | {
        "paid_on",
        "payment_method",
        "payment_note",
    }

    status = models.CharField(
        "statut", max_length=10, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT
    )
    due_date = models.DateField("date d'échéance", null=True, blank=True)
    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="réservation",
    )
    structured_reference = models.CharField("communication structurée", max_length=21, blank=True)
    paid_on = models.DateField("payée le", null=True, blank=True)
    payment_method = models.CharField(
        "mode de paiement", max_length=10, choices=PaymentMethod.choices, blank=True
    )
    payment_note = models.CharField("note de paiement", max_length=200, blank=True)

    class Meta:
        ordering = ["-issue_date", "-number", "-pk"]
        verbose_name = "facture"
        verbose_name_plural = "factures"

    @property
    def is_overdue(self) -> bool:
        return (
            self.status == InvoiceStatus.ISSUED
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )


class CreditNoteStatus(models.TextChoices):
    DRAFT = "draft", "Brouillon"
    ISSUED = "issued", "Émise"


class CreditNote(BillingDocument):
    status = models.CharField(
        "statut",
        max_length=10,
        choices=CreditNoteStatus.choices,
        default=CreditNoteStatus.DRAFT,
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name="credit_notes",
        verbose_name="facture corrigée",
    )
    reason = models.CharField("motif", max_length=300)

    class Meta:
        ordering = ["-issue_date", "-number", "-pk"]
        verbose_name = "note de crédit"
        verbose_name_plural = "notes de crédit"


class DocumentLine(models.Model):
    """One line of an invoice or credit note: quantity (periods) × unit price excl. VAT."""

    description = models.CharField("description", max_length=300)
    service_start = models.DateField("début de la prestation", null=True, blank=True)
    service_end = models.DateField("fin de la prestation", null=True, blank=True)
    quantity = models.PositiveIntegerField("quantité", validators=[MinValueValidator(1)])
    unit_price_excl_vat = models.DecimalField(
        "prix unitaire HTVA",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    line_total_excl_vat = models.DecimalField(
        "total HTVA", max_digits=10, decimal_places=2, editable=False
    )

    class Meta:
        abstract = True
        ordering = ["pk"]

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        self._refuse_if_issued()
        self.line_total_excl_vat = round_money(self.quantity * self.unit_price_excl_vat)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._refuse_if_issued()
        return super().delete(*args, **kwargs)

    def clean(self):
        if self.service_start and self.service_end and self.service_end < self.service_start:
            raise ValidationError({"service_end": "La fin est antérieure au début."})

    def _refuse_if_issued(self):
        if self.document.number:
            raise IssuedDocumentError("Document émis : ses lignes ne peuvent plus être modifiées.")


class InvoiceLine(DocumentLine):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")

    class Meta(DocumentLine.Meta):
        verbose_name = "ligne de facture"
        verbose_name_plural = "lignes de facture"

    @property
    def document(self):
        return self.invoice


class CreditNoteLine(DocumentLine):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")

    class Meta(DocumentLine.Meta):
        verbose_name = "ligne de note de crédit"
        verbose_name_plural = "lignes de note de crédit"

    @property
    def document(self):
        return self.credit_note
