from django import forms

from core.forms import PicoFormMixin
from storage.models import Row


class RowForm(PicoFormMixin, forms.ModelForm):
    class Meta:
        model = Row
        fields = ["code", "display_order", "length_override_m", "is_active", "notes"]
        widgets = {"notes": forms.TextInput()}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()
