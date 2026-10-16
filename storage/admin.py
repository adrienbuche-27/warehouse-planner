from django.contrib import admin

from storage.models import Booking, Row


@admin.register(Row)
class RowAdmin(admin.ModelAdmin):
    list_display = ["code", "display_order", "length_override_m", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "notes"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["vehicle", "row", "position", "start_date", "end_date", "periods", "status"]
    list_filter = ["status", "row"]
    search_fields = [
        "vehicle__plate",
        "vehicle__client__last_name",
        "vehicle__client__company_name",
    ]
    date_hierarchy = "start_date"
    autocomplete_fields = ["vehicle"]
    readonly_fields = [
        "end_date",
        "band_length_m",
        "price_per_band",
        "billed_length_m",
        "band_count",
        "price_per_period",
        "vat_regime",
        "vat_rate",
    ]
