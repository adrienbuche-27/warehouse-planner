"""Top-level URL configuration."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Gestion Stockage Camping-Cars"
admin.site.site_title = "Administration"
admin.site.index_title = "Administration (secours)"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Login, logout and password reset ("mot de passe oublié"), with French
    # templates in templates/registration/.
    path("compte/", include("django.contrib.auth.urls")),
    path("", include("core.urls")),
]
