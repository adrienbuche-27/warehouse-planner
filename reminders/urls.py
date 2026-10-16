from django.urls import path

from reminders import views

app_name = "reminders"

urlpatterns = [
    path("rappels/", views.reminder_list, name="reminder_list"),
]
