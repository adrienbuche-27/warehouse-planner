from django.contrib import admin

from storage.models import Row


@admin.register(Row)
class RowAdmin(admin.ModelAdmin):
    list_display = ["code", "display_order", "length_override_m", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "notes"]
