from django.contrib import admin

from core.models import AppSettings


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    """Fallback only: the settings are normally edited on the "Paramètres" page."""

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
