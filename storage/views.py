from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.forms import BulkRowCreateForm
from storage import services
from storage.forms import RowForm
from storage.models import Row


@require_POST
def row_bulk_create(request):
    """ "Créer N rangées" on the Paramètres page."""
    form = BulkRowCreateForm(request.POST)
    if form.is_valid():
        rows = services.create_rows(form.cleaned_data["count"])
        messages.success(
            request,
            f"{len(rows)} rangée(s) créée(s) : {rows[0].code} à {rows[-1].code}."
            if len(rows) > 1
            else f"Rangée {rows[0].code} créée.",
        )
    else:
        messages.error(request, "Nombre de rangées invalide.")
    return redirect(reverse("core:settings") + "#rangees")


def row_display(request, pk):
    """One read-only line of the rows table (HTMX: "Annuler" while editing)."""
    row = get_object_or_404(Row, pk=pk)
    return render(request, "storage/_row_display.html", {"row": _with_length(row)})


def row_edit(request, pk):
    """Inline edit of one line of the rows table (HTMX)."""
    row = get_object_or_404(Row, pk=pk)
    if request.method == "POST":
        form = RowForm(request.POST, instance=row)
        if form.is_valid():
            # Checks on existing bookings (CLAUDE.md, section 6.5) are added with bookings in M3.
            row = form.save()
            return render(request, "storage/_row_display.html", {"row": _with_length(row)})
    else:
        form = RowForm(instance=row)
    return render(request, "storage/_row_edit.html", {"row": row, "form": form})


def _with_length(row):
    row.length = row.effective_length
    return row
