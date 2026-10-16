# Which navigation item is highlighted for each page, by URL name prefix.
# When adding a page, add its URL name (or a prefix of it) here.
NAV_SECTIONS = [
    ("core:dashboard", "dashboard"),
    ("core:settings", "settings"),
    ("storage:row_", "settings"),
    ("storage:booking_", "bookings"),
    ("storage:planning", "planning"),
    ("invoicing:", "invoices"),
    ("reminders:", "dashboard"),  # reached from the dashboard
    ("clients:client_", "clients"),
    ("clients:vehicle_", "vehicles"),
]


def navigation(request):
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else ""
    section = next(
        (name for prefix, name in NAV_SECTIONS if view_name.startswith(prefix)),
        "",
    )
    return {"nav_section": section}
