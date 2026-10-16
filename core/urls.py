from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("parametres/", views.settings_page, name="settings"),
    path("parametres/email-test/", views.send_test_email, name="settings_test_email"),
    path("parametres/logo/", views.company_logo, name="settings_logo"),
]
