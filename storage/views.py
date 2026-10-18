import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from clients.models import Client, Vehicle
from core.forms import BulkRowCreateForm
from core.models import AppSettings
from invoicing import services as invoicing_services
from storage import planning as planning_module
from storage import services, warehouse_map
from storage.forms import (
    BookingForm,
    ExtendForm,
    QuickClientForm,
    QuickVehicleForm,
    RowForm,
    StatusDateForm,
)
from storage.models import DOCUMENTS, Booking, BookingStatus, Row, compute_end_date

MAX_VEHICLE_LENGTH = Decimal("20")  # same limit as the vehicle form


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
    saved = Row.objects.get(pk=pk)  # values before this edit
    context = {"row": row, "blocking_bookings": [], "overflow_bookings": []}
    if request.method == "POST":
        form = RowForm(request.POST, instance=row)
        if form.is_valid():
            # Section 6.5: refuse deactivating a row still in use, and ask for confirmation
            # when a shorter row would leave bookings without enough room.
            if saved.is_active and not row.is_active:
                context["blocking_bookings"] = services.bookings_preventing_deactivation(saved)
            if (
                not context.get("blocking_bookings")
                and row.effective_length < saved.effective_length
            ):
                overflow = services.bookings_not_fitting(
                    row_lengths={row.pk: row.length_override_m}
                )
                context["overflow_bookings"] = [b for b in overflow if b.row_id == row.pk]
            if context.get("blocking_bookings") or (
                context.get("overflow_bookings") and not request.POST.get("confirm_overflow")
            ):
                return render(request, "storage/_row_edit.html", {**context, "form": form})
            row = form.save()
            return render(request, "storage/_row_display.html", {"row": _with_length(row)})
    else:
        form = RowForm(instance=row)
    return render(request, "storage/_row_edit.html", {**context, "form": form})


def _with_length(row):
    row.length = row.effective_length
    return row


# --- Bookings ----------------------------------------------------------------

BOOKING_PAGE_SIZE = 50
STATUS_FILTERS = [
    ("en-cours", "En cours (réservées et en stock)"),
    *BookingStatus.choices,
    ("toutes", "Toutes"),
]


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def booking_list(request):
    status = request.GET.get("statut", "en-cours")
    row_id = request.GET.get("rangee", "")
    client_id = request.GET.get("client", "")
    date_from = _parse_date(request.GET.get("du"))
    date_to = _parse_date(request.GET.get("au"))
    query = request.GET.get("q", "").strip()
    documents = request.GET.get("documents", "")

    bookings = Booking.objects.select_related("vehicle__client", "row")
    if status == "en-cours":
        bookings = bookings.active()
    elif status in BookingStatus.values:
        bookings = bookings.filter(status=status)
    if documents == "a-completer":
        bookings = bookings.documents_incomplete()
    if row_id.isdigit():
        bookings = bookings.filter(row_id=row_id)
    if client_id.isdigit():
        bookings = bookings.filter(vehicle__client_id=client_id)
    if date_from or date_to:
        bookings = bookings.overlapping(
            date_from or datetime.date.min, date_to or datetime.date.max
        )
    for word in query.split():
        bookings = bookings.filter(
            Q(vehicle__plate__icontains=word)
            | Q(vehicle__client__first_name__icontains=word)
            | Q(vehicle__client__last_name__icontains=word)
            | Q(vehicle__client__company_name__icontains=word)
        )

    page = Paginator(bookings, BOOKING_PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "status": status,
        "status_filters": STATUS_FILTERS,
        "row_id": row_id,
        "rows": Row.objects.all(),
        "client_id": client_id,
        "clients": Client.objects.filter(vehicles__bookings__isnull=False).distinct(),
        "date_from": date_from,
        "date_to": date_to,
        "query": query,
        "documents": documents,
    }
    template = "storage/_booking_results.html" if _is_htmx(request) else "storage/booking_list.html"
    return render(request, template, context)


def _booking_form_page(request, form, booking=None):
    context = {
        "form": form,
        "booking": booking,
        "price_missing": AppSettings.load().price_per_band is None,
    }
    return render(request, "storage/booking_form.html", context)


def booking_create(request):
    """New booking. Planning and warehouse map links prefill it: ?rangee=<id>&debut=<yyyy-mm-dd>,
    and from the map also &position=<n>&periodes=<n>&vehicule=<id>."""
    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            try:
                booking = form.save()
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, f"Réservation créée : {booking}.")
                return redirect("storage:booking_detail", pk=booking.pk)
    else:
        initial = {"start_date": _parse_date(request.GET.get("debut")) or services.today()}
        prefill = [
            ("row", "rangee"),
            ("position", "position"),
            ("periods", "periodes"),
            ("client", "client"),
            ("vehicle", "vehicule"),
        ]
        for field, param in prefill:
            if request.GET.get(param, "").isdigit():
                initial[field] = request.GET[param]
        if "vehicle" in initial and "client" not in initial:
            vehicle = Vehicle.objects.filter(pk=initial["vehicle"]).first()
            if vehicle:
                initial["client"] = vehicle.client_id
        form = BookingForm(initial=initial)
    return _booking_form_page(request, form)


def booking_edit(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("vehicle", "row"), pk=pk)
    if not booking.is_active:
        messages.error(request, "Une réservation terminée ou annulée ne peut plus être modifiée.")
        return redirect("storage:booking_detail", pk=booking.pk)
    form = BookingForm(request.POST or None, instance=booking)
    if form.is_valid():
        form.save()
        messages.success(request, "Réservation enregistrée.")
        # Another vehicle may have another length, hence another number of bands.
        if change := services.refresh_price(booking):
            level = messages.INFO if change.applied else messages.WARNING
            messages.add_message(request, level, change.as_text())
        return redirect("storage:booking_detail", pk=booking.pk)
    return _booking_form_page(request, form, booking)


def booking_detail(request, pk, extend_form=None, extension=None):
    booking = get_object_or_404(Booking.objects.select_related("vehicle__client", "row"), pk=pk)
    context = {
        "booking": booking,
        "invoices": booking.invoices.all(),
        "reminders": booking.reminders.all(),
        "reminder_days": AppSettings.load().reminder_days_before_end,
        "uninvoiced_periods": invoicing_services.uninvoiced_periods(booking),
        "move_plans": services.move_plans(booking),
        "date_form": StatusDateForm(),
        "extend_form": extend_form or ExtendForm(initial={"added_periods": 1}),
        "extension": extension,
    }
    return render(request, "storage/booking_detail.html", context)


@require_POST
def booking_action(request, pk, action):
    """Status changes: Marquer en stock / Marquer sortie / Annuler."""
    booking = get_object_or_404(Booking, pk=pk)
    date_form = StatusDateForm(request.POST)
    date = date_form.cleaned_data["date"] if date_form.is_valid() else services.today()
    try:
        if action == "en-stock":
            services.mark_stored(booking, date)
            messages.success(
                request, f"{booking.vehicle.plate} est en stock depuis le {date:%d/%m/%Y}."
            )
        elif action == "sortie":
            services.mark_ended(booking, date)
            messages.success(request, f"{booking.vehicle.plate} est sorti le {date:%d/%m/%Y}.")
        elif action == "annuler":
            services.cancel(booking)
            messages.success(request, "Réservation annulée.")
        else:
            raise Http404
    except services.BookingActionError as exc:
        messages.error(request, str(exc))
    return redirect("storage:booking_detail", pk=booking.pk)


@require_POST
def booking_document(request, pk, document):
    """Record the check of the ID or the insurance of a booking (one click: valide, invalide or
    manquant, with an optional note)."""
    booking = get_object_or_404(Booking, pk=pk)
    if document not in DOCUMENTS:
        raise Http404
    status = request.POST.get("status", "")
    try:
        services.set_document_status(
            booking, document, status, request.user, request.POST.get("note", "")
        )
    except services.BookingActionError as exc:
        messages.error(request, str(exc))
    else:
        check = booking.document(document)
        messages.success(request, f"{check.label} : {check.status_label.lower()}.")
    return redirect(reverse("storage:booking_detail", args=[booking.pk]) + "#documents")


@require_POST
def booking_extend(request, pk):
    """ "Prolonger": refused if the vehicle no longer fits; blocking situations need ticking
    the confirmation box."""
    booking = get_object_or_404(Booking.objects.select_related("vehicle", "row"), pk=pk)
    form = ExtendForm(request.POST)
    if not form.is_valid():
        return booking_detail(request, pk, extend_form=form)
    added = form.cleaned_data["added_periods"]
    try:
        check = services.extend(booking, added, confirmed=form.cleaned_data["confirm_conflicts"])
    except services.BookingActionError as exc:
        messages.error(request, str(exc))
        return redirect("storage:booking_detail", pk=booking.pk)
    if not check.applied:
        # Blocking situations: show them and ask for confirmation.
        return booking_detail(request, pk, extend_form=form, extension=check)
    messages.success(
        request,
        f"Réservation prolongée de {added} période(s), jusqu'au {booking.end_date:%d/%m/%Y}. "
        "Créez la facture complémentaire dans la section Factures ci-dessous.",
    )
    return redirect("storage:booking_detail", pk=booking.pk)


# --- Booking form helpers (HTMX) ---------------------------------------------


def booking_vehicle_options(request):
    """Vehicle dropdown for the chosen client."""
    client_id = request.GET.get("client", "")
    vehicles = Vehicle.objects.none()
    if client_id.isdigit():
        vehicles = Vehicle.objects.filter(client_id=client_id, is_archived=False)
    selected = request.GET.get("selected", "")
    response = render(
        request,
        "storage/_vehicle_select.html",
        {"vehicles": vehicles, "selected": selected, "client_id": client_id},
    )
    return _vehicle_selected(response)


def _vehicle_selected(response):
    """Tell the booking form that the vehicle dropdown changed, so the price is recomputed
    (the price depends on the vehicle length). "After settle": once the new dropdown is in
    the page, so the price is computed for the newly selected vehicle."""
    response["HX-Trigger-After-Settle"] = "vehicle-selected"
    return response


def booking_summary(request):
    """End date and prices (bands, HT / TVA / TTC), recomputed while the form is filled."""
    start = _parse_date(request.GET.get("start_date"))
    periods = request.GET.get("periods", "")
    periods = int(periods) if periods.isdigit() and 0 < int(periods) <= 100 else None
    booking = None
    if request.GET.get("booking", "").isdigit():
        booking = Booking.objects.filter(pk=request.GET["booking"]).first()
    vehicle = None
    if request.GET.get("vehicle", "").isdigit():
        vehicle = Vehicle.objects.filter(pk=request.GET["vehicle"]).first()
    end = None
    if start and periods:
        end = compute_end_date(start, periods, AppSettings.load().period_days)
    context = {
        "end": end,
        "periods": periods,
        "vehicle": vehicle,
        "price": services.price_preview(vehicle, periods, booking),
        "price_missing": AppSettings.load().price_per_band is None,
    }
    return render(request, "storage/_booking_summary.html", context)


def booking_suggestions(request):
    """ "Proposer un emplacement": the 5 best rows and positions."""
    vehicle = Vehicle.objects.filter(pk=request.GET.get("vehicle") or 0).first()
    start = _parse_date(request.GET.get("start_date"))
    periods = request.GET.get("periods", "")
    booking = None
    if request.GET.get("booking", "").isdigit():
        booking = Booking.objects.filter(pk=request.GET["booking"]).first()
    context = {"missing": not (vehicle and start and periods.isdigit() and int(periods) > 0)}
    if not context["missing"]:
        end = compute_end_date(start, int(periods), AppSettings.load().period_days)
        context["suggestions"] = services.suggest_placements(vehicle, start, end, booking)[:5]
        context["already_booked"] = bool(services.vehicle_conflicts(vehicle, start, end, booking))
    return render(request, "storage/_suggestions.html", context)


def booking_map(request):
    """Warehouse map in the booking form, for the vehicle and dates being booked."""
    vehicle = Vehicle.objects.filter(pk=request.GET.get("vehicle") or 0).first()
    start = _parse_date(request.GET.get("start_date"))
    periods = request.GET.get("periods", "")
    booking = None
    if request.GET.get("booking", "").isdigit():
        booking = Booking.objects.filter(pk=request.GET["booking"]).first()
    context = {
        "missing": not (vehicle and start and periods.isdigit() and 0 < int(periods) <= 100),
        "selected_row": request.GET.get("row", ""),
    }
    if not context["missing"]:
        end = compute_end_date(start, int(periods), AppSettings.load().period_days)
        context["already_booked"] = bool(services.vehicle_conflicts(vehicle, start, end, booking))
        context["map"] = warehouse_map.build_map(start, end, vehicle, booking)
    return render(request, "storage/_booking_map.html", context)


def booking_quick_client(request):
    """ "+ Nouveau client" inside the booking form.

    Once saved, the new client is selected and the new-vehicle form opens for them, so the
    booking can go on without leaving the page.
    """
    if request.method == "POST":
        form = QuickClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            context = {
                "clients": Client.objects.filter(is_archived=False),
                "selected": str(client.pk),
                "new_client": client,
                "vehicle_form": QuickVehicleForm(),
            }
            return _vehicle_selected(render(request, "storage/_client_select.html", context))
        response = render(request, "storage/_quick_client_form.html", {"form": form})
        response["HX-Retarget"] = "#quick-client"
        return response
    return render(request, "storage/_quick_client_form.html", {"form": QuickClientForm()})


def booking_quick_vehicle(request):
    """ "+ Nouveau véhicule" inside the booking form."""
    client_id = request.POST.get("client") or request.GET.get("client", "")
    client = Client.objects.filter(pk=client_id).first() if str(client_id).isdigit() else None
    if client is None:
        return render(request, "storage/_quick_vehicle_form.html", {"no_client": True})
    if request.method == "POST":
        form = QuickVehicleForm(request.POST)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.client = client
            vehicle.save()
            vehicles = Vehicle.objects.filter(client=client, is_archived=False)
            context = {
                "vehicles": vehicles,
                "selected": str(vehicle.pk),
                "client_id": client.pk,
                "close_quick_form": True,
            }
            return _vehicle_selected(render(request, "storage/_vehicle_select.html", context))
        response = render(
            request, "storage/_quick_vehicle_form.html", {"form": form, "client": client}
        )
        response["HX-Retarget"] = "#quick-vehicle"
        return response
    form = QuickVehicleForm()
    return render(request, "storage/_quick_vehicle_form.html", {"form": form, "client": client})


# --- Planning ----------------------------------------------------------------


def _parse_decimal(value):
    """A positive number typed with a comma or a dot ("7,40"), or None."""
    try:
        number = Decimal((value or "").replace(",", "."))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def planning(request):
    """Grid of rows × 2-week windows, from the Monday of the current week by default."""
    today = services.today()
    start = planning_module.monday_of(_parse_date(request.GET.get("debut")) or today)
    min_free = _parse_decimal(request.GET.get("libre"))
    grid = planning_module.build_grid(start, min_free_m=min_free)
    period_days = AppSettings.load().period_days
    step = datetime.timedelta(days=period_days)
    context = {
        "grid": grid,
        "today": today,
        "min_free": min_free,
        "nav": {
            "page_back": start - step * planning_module.WINDOW_COUNT,
            "back": start - step,
            "today": planning_module.monday_of(today),
            "forward": start + step,
            "page_forward": start + step * planning_module.WINDOW_COUNT,
        },
    }
    return render(request, "storage/planning.html", context)


MAX_PLAN_DAYS = 366  # longest range shown on "Plan de l'entrepôt"


def planning_map(request):
    """ "Plan de l'entrepôt" (space management): who is where on a day (today by default) or
    over a range of dates, with the vehicles boxed in when entering or leaving."""
    today = services.today()
    day = _parse_date(request.GET.get("date")) or today
    end = _parse_date(request.GET.get("au"))
    error = ""
    if end is not None and end < day:
        error, end = (
            "La date de fin est antérieure à la date de début : un seul jour est affiché.",
            None,
        )
    elif end is not None and (end - day).days > MAX_PLAN_DAYS:
        error, end = "Période trop longue (un an au maximum) : un seul jour est affiché.", None
    end = end or day
    span = end - day

    def link(first):  # same length of time, shifted
        params = {"date": first.isoformat()}
        if span:
            params["au"] = (first + span).isoformat()
        return "?" + urlencode(params)

    week = datetime.timedelta(days=7)
    context = {
        "map": warehouse_map.build_map(day, end, with_blockings=True),
        "day": day,
        "end": end,
        "is_range": bool(span),
        "error": error,
        "nav": {"back": link(day - week), "today": link(today), "forward": link(day + week)},
    }
    return render(request, "storage/warehouse_map.html", context)


def booking_find(request):
    """ "Trouver un emplacement": where to book a van (a registered vehicle, or just a length)
    for a stay, before creating the booking. Each place links to the prefilled booking form."""
    searched = "date" in request.GET
    day = _parse_date(request.GET.get("date")) or services.today()
    periods = request.GET.get("periodes", "")
    periods = int(periods) if periods.isdigit() and 0 < int(periods) <= 100 else None
    vehicle = Vehicle.objects.filter(pk=request.GET.get("vehicule") or 0).first()
    raw_length = request.GET.get("longueur", "").strip()
    length = _parse_decimal(raw_length)
    if length is not None and length > MAX_VEHICLE_LENGTH:
        length = None

    errors = []
    if searched and periods is None:
        errors.append("Indiquez le nombre de périodes (de 1 à 100).")
    if searched and vehicle is None:
        if raw_length and length is None:
            errors.append("Longueur invalide : indiquez une longueur entre 0,01 et 20 m.")
        elif length is None:
            errors.append("Indiquez la longueur du véhicule ou choisissez un véhicule enregistré.")
    van = vehicle or (warehouse_map.planned_vehicle(length) if length else None)

    context = {
        "day": day,
        "periods": periods,
        "length": length,
        "raw_length": raw_length if vehicle is None else "",
        "vehicle": vehicle,
        "vehicles": Vehicle.objects.active().select_related("client"),
        "errors": errors,
    }
    if van is not None and periods is not None:
        end = compute_end_date(day, periods, AppSettings.load().period_days)
        found = warehouse_map.build_map(day, end, van)
        context.update(
            end=end,
            map=found,
            best=found.suggestions[:5],
            already_booked=bool(vehicle and services.vehicle_conflicts(vehicle, day, end)),
        )
    return render(request, "storage/booking_find.html", context)


def planning_cell(request, row_pk, start):
    """Panel opened by clicking a cell: the vehicles of the row during the window."""
    row = get_object_or_404(Row, pk=row_pk)
    window_start = _parse_date(start)
    if window_start is None:
        raise Http404
    period_days = AppSettings.load().period_days
    window_end = window_start + datetime.timedelta(days=period_days - 1)
    context = {
        "row": row,
        "window_start": window_start,
        "window_end": window_end,
        "vehicles": planning_module.cell_details(row, window_start, window_end),
        # A new booking cannot start in the past: use today if the window has begun.
        "new_booking_start": max(window_start, services.today()),
    }
    return render(request, "storage/_planning_cell.html", context)
