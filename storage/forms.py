from django import forms
from django.db.models import Q
from django.utils import timezone

from clients.models import Client, Vehicle, normalize_plate
from core.formatting import format_metres
from core.forms import PicoFormMixin
from core.models import AppSettings
from storage import services
from storage.models import Booking, Row, compute_end_date


class RowForm(PicoFormMixin, forms.ModelForm):
    class Meta:
        model = Row
        fields = ["code", "display_order", "length_override_m", "is_active", "notes"]
        widgets = {"notes": forms.TextInput()}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class DateInput(forms.DateInput):
    """Browser date picker. It always sends and expects yyyy-mm-dd."""

    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m-%d")


class BookingForm(PicoFormMixin, forms.ModelForm):
    """Create or edit a booking. Runs the fit check and asks to confirm blocking situations."""

    client = forms.ModelChoiceField(queryset=Client.objects.none(), label="Client")
    confirm_conflicts = forms.BooleanField(
        required=False, label="Je confirme malgré les déplacements de véhicules nécessaires"
    )

    class Meta:
        model = Booking
        fields = ["client", "vehicle", "start_date", "periods", "row", "position", "notes"]
        widgets = {
            "start_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.warnings = []
        instance = self.instance
        if instance.pk and "client" not in self.initial:
            self.initial["client"] = instance.vehicle.client_id

        self.fields["client"].queryset = Client.objects.filter(
            Q(is_archived=False) | Q(pk=self.initial.get("client"))
        )
        client_id = self.data.get("client") or self.initial.get("client")
        vehicles = Vehicle.objects.none()
        if client_id and str(client_id).isdigit():
            vehicles = Vehicle.objects.filter(client_id=client_id).filter(
                Q(is_archived=False) | Q(pk=instance.vehicle_id)
            )
        self.fields["vehicle"].queryset = vehicles
        self.fields["vehicle"].empty_label = "Choisissez d'abord le client"
        self.fields["row"].queryset = Row.objects.filter(Q(is_active=True) | Q(pk=instance.row_id))
        self.fields["row"].empty_label = "— Choisir une rangée —"
        self.fields["position"].help_text = "1 = le plus proche de l'allée."
        self.fields["periods"].help_text = f"Périodes de {AppSettings.load().period_days} jours."
        if not instance.pk:
            self.fields["periods"].initial = 1

    def clean(self):
        cleaned = super().clean()
        client, vehicle = cleaned.get("client"), cleaned.get("vehicle")
        if client and vehicle and vehicle.client_id != client.pk:
            self.add_error("vehicle", "Ce véhicule n'appartient pas à ce client.")
            return cleaned
        required = ["vehicle", "start_date", "periods", "row", "position"]
        if self.errors or any(cleaned.get(name) is None for name in required):
            return cleaned

        start, row, position = cleaned["start_date"], cleaned["row"], cleaned["position"]
        end = compute_end_date(start, cleaned["periods"], AppSettings.load().period_days)
        exclude = self.instance if self.instance.pk else None

        fit = services.check_fit(row, vehicle, start, end, position, exclude_booking=exclude)
        self.fit = fit
        for other in fit.vehicle_conflicts:
            self.add_error(
                "vehicle",
                f"Ce véhicule est déjà réservé du {other.start_date:%d/%m/%Y} au "
                f"{other.end_date:%d/%m/%Y} ({other.row.code}).",
            )
        for other in fit.position_conflicts:
            self.add_error(
                "position",
                f"Position déjà occupée par {other.vehicle.plate} du "
                f"{other.start_date:%d/%m/%Y} au {other.end_date:%d/%m/%Y}.",
            )
        if fit.length_conflicts:
            plates = ", ".join(b.vehicle.plate for b in fit.length_conflicts)
            self.add_error(
                "row",
                f"Le véhicule ne tient pas dans la rangée {row.code} : il faudrait "
                f"{format_metres(fit.peak_occupancy_m)} pour {format_metres(fit.row_length_m)} "
                f"disponibles (déjà présents : {plates}).",
            )
        if not fit.ok:
            return cleaned

        self.warnings = services.placement_warnings(row, vehicle, start, end, position, exclude)
        if self.warnings and not cleaned.get("confirm_conflicts"):
            self.add_error(
                "confirm_conflicts",
                "Cet emplacement implique de déplacer des véhicules : cochez « Je confirme » "
                "ou choisissez un autre emplacement.",
            )
        return cleaned


class QuickVehicleForm(PicoFormMixin, forms.ModelForm):
    """ "+ Nouveau véhicule" inside the booking form (fields prefixed "qv-")."""

    prefix = "qv"

    class Meta:
        model = Vehicle
        fields = ["plate", "brand", "model", "length_m", "height_m"]

    def clean_plate(self):
        return normalize_plate(self.cleaned_data["plate"])


class StatusDateForm(forms.Form):
    """Date for "Marquer en stock" / "Marquer sortie"."""

    date = forms.DateField(label="Date", widget=DateInput(), initial=timezone.localdate)


class ExtendForm(PicoFormMixin, forms.Form):
    added_periods = forms.IntegerField(label="Périodes à ajouter", min_value=1, max_value=52)
    confirm_conflicts = forms.BooleanField(required=False)
