from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from clients.models import Client
from core.forms import PicoFormMixin
from invoicing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine, PaymentMethod
from storage.forms import DateInput

LINE_FIELDS = ["description", "service_start", "service_end", "quantity", "unit_price_excl_vat"]
LINE_WIDGETS = {
    "service_start": DateInput(),
    "service_end": DateInput(),
    "quantity": forms.NumberInput(attrs={"min": 1}),
    "unit_price_excl_vat": forms.NumberInput(attrs={"step": "0.01", "min": 0}),
}

InvoiceLineFormSet = inlineformset_factory(
    Invoice, InvoiceLine, fields=LINE_FIELDS, widgets=LINE_WIDGETS, extra=1, can_delete=True
)
CreditNoteLineFormSet = inlineformset_factory(
    CreditNote,
    CreditNoteLine,
    fields=LINE_FIELDS,
    widgets=LINE_WIDGETS,
    extra=0,
    can_delete=True,
)


class ManualInvoiceForm(PicoFormMixin, forms.Form):
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(is_archived=False), label="Client"
    )


class PaymentForm(PicoFormMixin, forms.Form):
    paid_on = forms.DateField(label="Payée le", widget=DateInput(), initial=timezone.localdate)
    payment_method = forms.ChoiceField(
        label="Mode de paiement", choices=PaymentMethod.choices, initial=PaymentMethod.TRANSFER
    )
    payment_note = forms.CharField(label="Note", required=False, max_length=200)


class CreditNoteReasonForm(PicoFormMixin, forms.ModelForm):
    class Meta:
        model = CreditNote
        fields = ["reason"]
        widgets = {"reason": forms.TextInput(attrs={"placeholder": "Ex. erreur de période"})}
