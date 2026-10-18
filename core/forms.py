from django import forms
from django.utils.text import slugify

from core.models import AppSettings
from storage.services import MAX_ROWS_PER_BULK_CREATE

# Field groups shown on the "Paramètres" page, in this order.
SETTINGS_GROUPS = [
    ("Entrepôt", ["default_row_length_m", "vehicle_gap_m", "period_days"]),
    (
        "Tarifs & TVA",
        ["band_length_m", "price_per_band", "vat_regime", "vat_rate", "payment_terms_days"],
    ),
    (
        "Société (mentions sur factures)",
        [
            "company_name",
            "company_legal_form",
            "company_address",
            "company_vat_number",
            "company_bce_number",
            "company_rpm",
            "company_iban",
            "company_bic",
            "company_email",
            "company_phone",
            "company_logo",
        ],
    ),
    (
        "Rappels",
        [
            "reminder_days_before_end",
            "admin_notification_emails",
            "client_reminder_subject",
            "client_reminder_body",
        ],
    ),
]


class PicoFormMixin:
    """Mark invalid fields with aria-invalid="true", which Pico.css shows in red."""

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                self.fields[name].widget.attrs["aria-invalid"] = "true"


class AppSettingsForm(PicoFormMixin, forms.ModelForm):
    # Fields shown across the full width of their group (long texts).
    WIDE_FIELDS = {
        "company_address",
        "company_logo",
        "admin_notification_emails",
        "client_reminder_subject",
        "client_reminder_body",
    }

    class Meta:
        model = AppSettings
        fields = [name for _, names in SETTINGS_GROUPS for name in names]
        widgets = {
            "company_address": forms.Textarea(attrs={"rows": 3}),
            "admin_notification_emails": forms.TextInput(
                attrs={"placeholder": "marie@example.be, paul@example.be"}
            ),
            "client_reminder_body": forms.Textarea(attrs={"rows": 14}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Not required in the database (no sensible default), but needed before any booking.
        self.fields["price_per_band"].required = True

    def groups(self):
        """[(title, anchor, [(bound field, is_wide), ...]), ...] for the template."""
        return [
            (title, slugify(title), [(self[name], name in self.WIDE_FIELDS) for name in names])
            for title, names in SETTINGS_GROUPS
        ]


class BulkRowCreateForm(PicoFormMixin, forms.Form):
    count = forms.IntegerField(
        label="Nombre de rangées à créer",
        min_value=1,
        max_value=MAX_ROWS_PER_BULK_CREATE,
        initial=10,
    )
