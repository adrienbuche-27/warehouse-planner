"""Search for clients and vehicles."""

from django.db.models import Q, QuerySet

from clients.models import Client, Vehicle

CLIENT_SEARCH_FIELDS = [
    "first_name",
    "last_name",
    "company_name",
    "email",
    "phone",
    "city",
    "vat_number",
    "vehicles__plate",
]
VEHICLE_SEARCH_FIELDS = [
    "plate",
    "brand",
    "model",
    "client__first_name",
    "client__last_name",
    "client__company_name",
]


def _word_filter(query: str, fields: list[str]) -> Q:
    """Every word of the query must appear in at least one of the fields.

    "jean dupont" finds "Jean Dupont"; "dupont 1-ABC" finds Dupont's vehicle 1-ABC-123.
    """
    condition = Q()
    for word in query.split():
        word_condition = Q()
        for field in fields:
            word_condition |= Q(**{f"{field}__icontains": word})
        condition &= word_condition
    return condition


def search_clients(
    query: str = "", client_type: str = "", include_archived: bool = False
) -> QuerySet[Client]:
    clients = Client.objects.all()
    if not include_archived:
        clients = clients.filter(is_archived=False)
    if client_type:
        clients = clients.filter(client_type=client_type)
    if query.strip():
        clients = clients.filter(_word_filter(query, CLIENT_SEARCH_FIELDS)).distinct()
    return clients


def search_vehicles(query: str = "", include_archived: bool = False) -> QuerySet[Vehicle]:
    vehicles = Vehicle.objects.select_related("client")
    if not include_archived:
        vehicles = vehicles.active()
    if query.strip():
        vehicles = vehicles.filter(_word_filter(query, VEHICLE_SEARCH_FIELDS)).distinct()
    return vehicles
