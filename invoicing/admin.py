"""Fallback admin. Issued documents are read-only and can never be deleted (section 8.2)."""

from django.contrib import admin

from invoicing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine, NumberSequence


class ReadOnlyWhenIssuedMixin:
    def has_delete_permission(self, request, obj=None):
        return obj is not None and obj.is_draft

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and not obj.is_draft:
            return [field.name for field in self.model._meta.fields]
        return ["number", "issue_date", "pdf_file", "total_excl_vat", "total_vat", "total_incl_vat"]

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # bulk delete would bypass the per-object check
        return actions


class LineInlineMixin:
    extra = 0
    readonly_fields = ["line_total_excl_vat"]

    def _issued(self, obj):
        return obj is not None and not obj.is_draft

    def has_add_permission(self, request, obj=None):
        return not self._issued(obj)

    def has_change_permission(self, request, obj=None):
        return not self._issued(obj)

    def has_delete_permission(self, request, obj=None):
        return not self._issued(obj)


class InvoiceLineInline(LineInlineMixin, admin.TabularInline):
    model = InvoiceLine


class CreditNoteLineInline(LineInlineMixin, admin.TabularInline):
    model = CreditNoteLine


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyWhenIssuedMixin, admin.ModelAdmin):
    list_display = ["__str__", "client", "issue_date", "due_date", "total_incl_vat", "status"]
    list_filter = ["status"]
    search_fields = ["number", "client_name", "client__last_name", "client__company_name"]
    inlines = [InvoiceLineInline]


@admin.register(CreditNote)
class CreditNoteAdmin(ReadOnlyWhenIssuedMixin, admin.ModelAdmin):
    list_display = ["__str__", "invoice", "issue_date", "total_incl_vat", "status"]
    search_fields = ["number", "invoice__number", "client_name"]
    inlines = [CreditNoteLineInline]


@admin.register(NumberSequence)
class NumberSequenceAdmin(admin.ModelAdmin):
    list_display = ["kind", "year", "last_value"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
