from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from clients import services
from clients.forms import ClientForm, VehicleForm
from clients.models import Client, ClientType, Vehicle
from core.services import protected_objects
from invoicing.services import outstanding_balance
from storage.models import Booking

PAGE_SIZE = 50


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


# --- Clients -----------------------------------------------------------------


def client_list(request):
    query = request.GET.get("q", "").strip()
    client_type = request.GET.get("type", "")
    include_archived = request.GET.get("archives") == "1"
    clients = services.search_clients(query, client_type, include_archived)
    page = Paginator(clients.prefetch_related("vehicles"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    context = {
        "page": page,
        "query": query,
        "client_type": client_type,
        "include_archived": include_archived,
        "client_types": ClientType.choices,
    }
    # Live search (HTMX) only replaces the results, not the whole page.
    template = "clients/_client_results.html" if _is_htmx(request) else "clients/client_list.html"
    return render(request, template, context)


def client_create(request):
    form = ClientForm(request.POST or None)
    if form.is_valid():
        client = form.save()
        messages.success(request, f"Client « {client} » créé.")
        return redirect("clients:client_detail", pk=client.pk)
    return render(request, "clients/client_form.html", {"form": form})


def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    bookings = Booking.objects.filter(vehicle__client=client).select_related("vehicle", "row")
    context = {
        "client": client,
        "vehicles": client.vehicles.all(),
        "bookings": bookings.order_by("-start_date"),
        "invoices": client.invoice_set.all(),
        "outstanding": outstanding_balance(client),
    }
    return render(request, "clients/client_detail.html", context)


def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST or None, instance=client)
    if form.is_valid():
        form.save()
        messages.success(request, "Client enregistré.")
        return redirect("clients:client_detail", pk=client.pk)
    return render(request, "clients/client_form.html", {"form": form, "client": client})


@require_POST
def client_toggle_archive(request, pk):
    client = get_object_or_404(Client, pk=pk)
    client.is_archived = not client.is_archived
    client.save(update_fields=["is_archived", "updated_at"])
    if client.is_archived:
        with_vehicles = ", ainsi que ses véhicules" if client.vehicles.exists() else ""
        messages.success(request, f"Client « {client} » archivé{with_vehicles}.")
    else:
        messages.success(request, f"Client « {client} » restauré.")
    return redirect("clients:client_detail", pk=client.pk)


def client_delete(request, pk):
    """Delete a client and its vehicles, unless bookings or invoices are linked to them."""
    client = get_object_or_404(Client, pk=pk)
    blockers = protected_objects(client)
    if request.method == "POST":
        if blockers:
            messages.error(request, "Ce client ne peut pas être supprimé. Archivez-le plutôt.")
            return redirect("clients:client_detail", pk=client.pk)
        name = str(client)
        client.delete()
        messages.success(request, f"Client « {name} » supprimé.")
        return redirect("clients:client_list")
    context = {"client": client, "vehicles": client.vehicles.all(), "blockers": blockers}
    return render(request, "clients/client_confirm_delete.html", context)


# --- Vehicles ----------------------------------------------------------------


def vehicle_list(request):
    query = request.GET.get("q", "").strip()
    include_archived = request.GET.get("archives") == "1"
    vehicles = services.search_vehicles(query, include_archived)
    page = Paginator(vehicles, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {"page": page, "query": query, "include_archived": include_archived}
    template = "clients/_vehicle_results.html" if _is_htmx(request) else "clients/vehicle_list.html"
    return render(request, template, context)


def vehicle_create(request):
    initial = {}
    client_id = request.GET.get("client")
    if client_id and client_id.isdigit():
        initial["client"] = client_id
    form = VehicleForm(request.POST or None, initial=initial)
    if form.is_valid():
        vehicle = form.save()
        messages.success(request, f"Véhicule {vehicle} ajouté.")
        return redirect("clients:vehicle_detail", pk=vehicle.pk)
    return render(request, "clients/vehicle_form.html", {"form": form})


def vehicle_detail(request, pk):
    vehicle = get_object_or_404(Vehicle.objects.select_related("client"), pk=pk)
    bookings = vehicle.bookings.select_related("row").order_by("-start_date")
    return render(
        request, "clients/vehicle_detail.html", {"vehicle": vehicle, "bookings": bookings}
    )


def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    form = VehicleForm(request.POST or None, instance=vehicle)
    if form.is_valid():
        form.save()
        messages.success(request, "Véhicule enregistré.")
        return redirect("clients:vehicle_detail", pk=vehicle.pk)
    return render(request, "clients/vehicle_form.html", {"form": form, "vehicle": vehicle})


@require_POST
def vehicle_toggle_archive(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle.is_archived = not vehicle.is_archived
    vehicle.save(update_fields=["is_archived"])
    messages.success(
        request, f"Véhicule {vehicle} {'archivé' if vehicle.is_archived else 'restauré'}."
    )
    return redirect("clients:vehicle_detail", pk=vehicle.pk)


def vehicle_delete(request, pk):
    """Delete a vehicle, unless bookings are linked to it."""
    vehicle = get_object_or_404(Vehicle.objects.select_related("client"), pk=pk)
    blockers = protected_objects(vehicle)
    if request.method == "POST":
        if blockers:
            messages.error(request, "Ce véhicule ne peut pas être supprimé. Archivez-le plutôt.")
            return redirect("clients:vehicle_detail", pk=vehicle.pk)
        plate, client = vehicle.plate, vehicle.client
        vehicle.delete()
        messages.success(request, f"Véhicule {plate} supprimé.")
        return redirect("clients:client_detail", pk=client.pk)
    context = {"vehicle": vehicle, "blockers": blockers}
    return render(request, "clients/vehicle_confirm_delete.html", context)
