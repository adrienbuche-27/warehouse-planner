from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils.dateparse import parse_date

from reminders.models import ReminderKind, ReminderLog

PAGE_SIZE = 50


def _parse_date(value):
    try:
        return parse_date(value or "")
    except ValueError:
        return None


def reminder_list(request):
    """ "Rappels": every reminder email sent or attempted (client, admins, daily digest)."""
    kind = request.GET.get("type", "")
    result = request.GET.get("resultat", "")
    date_from = _parse_date(request.GET.get("du"))
    date_to = _parse_date(request.GET.get("au"))
    query = request.GET.get("q", "").strip()

    logs = ReminderLog.objects.select_related("booking__vehicle__client", "booking__row")
    if kind in ReminderKind.values:
        logs = logs.filter(kind=kind)
    if result == "ok":
        logs = logs.filter(success=True)
    elif result == "echec":
        logs = logs.filter(success=False)
    if date_from:
        logs = logs.filter(sent_at__date__gte=date_from)
    if date_to:
        logs = logs.filter(sent_at__date__lte=date_to)
    for word in query.split():
        logs = logs.filter(
            Q(booking__vehicle__plate__icontains=word)
            | Q(recipients__icontains=word)
            | Q(booking__vehicle__client__last_name__icontains=word)
            | Q(booking__vehicle__client__company_name__icontains=word)
        )

    page = Paginator(logs, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "kinds": ReminderKind.choices,
        "kind": kind,
        "result": result,
        "date_from": date_from,
        "date_to": date_to,
        "query": query,
    }
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "reminders/_reminder_results.html" if is_htmx else "reminders/reminder_list.html"
    return render(request, template, context)
