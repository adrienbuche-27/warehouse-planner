from django.urls import path

from clients import views

app_name = "clients"

urlpatterns = [
    path("clients/", views.client_list, name="client_list"),
    path("clients/nouveau/", views.client_create, name="client_create"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("clients/<int:pk>/modifier/", views.client_edit, name="client_edit"),
    path("clients/<int:pk>/archiver/", views.client_toggle_archive, name="client_archive"),
    path("clients/<int:pk>/supprimer/", views.client_delete, name="client_delete"),
    path("vehicules/", views.vehicle_list, name="vehicle_list"),
    path("vehicules/nouveau/", views.vehicle_create, name="vehicle_create"),
    path("vehicules/<int:pk>/", views.vehicle_detail, name="vehicle_detail"),
    path("vehicules/<int:pk>/modifier/", views.vehicle_edit, name="vehicle_edit"),
    path("vehicules/<int:pk>/archiver/", views.vehicle_toggle_archive, name="vehicle_archive"),
    path("vehicules/<int:pk>/supprimer/", views.vehicle_delete, name="vehicle_delete"),
]
