from django import forms
from django.db.models import Q

from clients.models import Client, Vehicle, normalize_plate
from core.forms import PicoFormMixin


class ClientForm(PicoFormMixin, forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "client_type",
            "first_name",
            "last_name",
            "company_name",
            "vat_number",
            "email",
            "phone",
            "street",
            "postal_code",
            "city",
            "country",
            "notes",
        ]
        widgets = {
            "client_type": forms.RadioSelect,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class VehicleForm(PicoFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ["client", "plate", "brand", "model", "length_m", "height_m", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Archived clients cannot receive new vehicles, but keep the current owner selectable.
        self.fields["client"].queryset = Client.objects.filter(
            Q(is_archived=False) | Q(pk=self.instance.client_id)
        )
        self.fields["plate"].help_text = "Enregistrée en majuscules, sans espaces."

    def clean_plate(self):
        return normalize_plate(self.cleaned_data["plate"])
