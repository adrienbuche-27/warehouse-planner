from django.contrib import admin

from reminders.models import ReminderLog


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ["sent_at", "kind", "booking", "recipients", "success"]
    list_filter = ["kind", "success"]
    search_fields = ["booking__vehicle__plate", "recipients", "error_message"]
    readonly_fields = [field.name for field in ReminderLog._meta.fields]

    def has_add_permission(self, request):
        return False
