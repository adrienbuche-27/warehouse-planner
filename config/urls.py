"""Top-level URL configuration."""

from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "Gestion Stockage Camping-Cars"
admin.site.site_title = "Administration"
admin.site.index_title = "Administration (secours)"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Browsers ask for /favicon.ico on their own, even on pages without the icon link.
    path(
        "favicon.ico",
        login_not_required(RedirectView.as_view(url=static("img/logo-placeholder.svg"))),
    ),
    # Login, logout and password reset ("mot de passe oublié"), with French
    # templates in templates/registration/.
    path("compte/", include("django.contrib.auth.urls")),
    path("", include("core.urls")),
    path("", include("storage.urls")),
    path("", include("clients.urls")),
    path("", include("invoicing.urls")),
]
