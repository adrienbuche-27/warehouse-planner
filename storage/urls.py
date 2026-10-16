from django.urls import path

from storage import views

app_name = "storage"

urlpatterns = [
    path("parametres/rangees/creer/", views.row_bulk_create, name="row_bulk_create"),
    path("parametres/rangees/<int:pk>/", views.row_display, name="row_display"),
    path("parametres/rangees/<int:pk>/modifier/", views.row_edit, name="row_edit"),
]
