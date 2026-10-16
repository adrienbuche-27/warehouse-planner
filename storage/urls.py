from django.urls import path

from storage import views

app_name = "storage"

urlpatterns = [
    # Rows (on the Paramètres page)
    path("parametres/rangees/creer/", views.row_bulk_create, name="row_bulk_create"),
    path("parametres/rangees/<int:pk>/", views.row_display, name="row_display"),
    path("parametres/rangees/<int:pk>/modifier/", views.row_edit, name="row_edit"),
    # Planning
    path("planning/", views.planning, name="planning"),
    path("planning/plan/", views.planning_map, name="planning_map"),
    path(
        "planning/rangee/<int:row_pk>/<str:start>/",
        views.planning_cell,
        name="planning_cell",
    ),
    # Bookings
    path("reservations/", views.booking_list, name="booking_list"),
    path("reservations/nouvelle/", views.booking_create, name="booking_create"),
    path("reservations/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("reservations/<int:pk>/modifier/", views.booking_edit, name="booking_edit"),
    path("reservations/<int:pk>/prolonger/", views.booking_extend, name="booking_extend"),
    path(
        "reservations/<int:pk>/<str:action>/",
        views.booking_action,
        name="booking_action",
    ),
    # Booking form helpers (HTMX)
    path("reservations/aide/vehicules/", views.booking_vehicle_options, name="booking_vehicles"),
    path("reservations/aide/calcul/", views.booking_summary, name="booking_summary"),
    path(
        "reservations/aide/suggestions/",
        views.booking_suggestions,
        name="booking_suggestions",
    ),
    path("reservations/aide/plan/", views.booking_map, name="booking_map"),
    path(
        "reservations/aide/nouveau-client/",
        views.booking_quick_client,
        name="booking_quick_client",
    ),
    path(
        "reservations/aide/nouveau-vehicule/",
        views.booking_quick_vehicle,
        name="booking_quick_vehicle",
    ),
]
