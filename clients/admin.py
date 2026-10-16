from django.contrib import admin

from clients.models import Client, Vehicle


class VehicleInline(admin.TabularInline):
    model = Vehicle
    extra = 0
    fields = ["plate", "brand", "model", "length_m", "is_archived"]


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["display_name", "client_type", "email", "phone", "city", "is_archived"]
    list_filter = ["client_type", "is_archived"]
    search_fields = ["first_name", "last_name", "company_name", "email", "vat_number"]
    inlines = [VehicleInline]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["plate", "brand", "model", "length_m", "client", "is_archived"]
    list_filter = ["is_archived"]
    search_fields = ["plate", "brand", "model", "client__last_name", "client__company_name"]
    autocomplete_fields = ["client"]
