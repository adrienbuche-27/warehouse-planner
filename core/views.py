import logging
import smtplib

from django.contrib import messages
from django.core.mail import send_mail
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from core import dashboard as dashboard_data
from core.forms import AppSettingsForm, BulkRowCreateForm
from core.models import AppSettings
from core.validators import REMINDER_PLACEHOLDERS
from storage import services
from storage.models import Row

logger = logging.getLogger(__name__)


def dashboard(request):
    """Tableau de bord: today's figures, what is coming in the next 14 days, two charts."""
    today = timezone.localdate()
    context = {
        "today": today,
        "has_rows": Row.objects.filter(is_active=True).exists(),
        "occupancy": dashboard_data.occupancy_on(today),
        "active_bookings": dashboard_data.active_booking_count(),
        "invoices": dashboard_data.invoice_figures(today),
        "ending_soon": dashboard_data.ending_soon(today),
        "upcoming_entries": dashboard_data.upcoming_entries(today),
        "failed_reminders": dashboard_data.failed_reminders(today),
        "forecast_chart": dashboard_data.occupancy_forecast_chart(today),
        "revenue_chart": dashboard_data.revenue_chart(today),
        "upcoming_days": dashboard_data.UPCOMING_DAYS,
    }
    return render(request, "core/dashboard.html", context)


def settings_page(request):
    """Paramètres: the AppSettings form, the rows table and the test email button."""
    app_settings = AppSettings.load()
    overflow_bookings = []
    if request.method == "POST":
        form = AppSettingsForm(request.POST, request.FILES, instance=app_settings)
        if form.is_valid():
            overflow = _bookings_overflowing_new_settings(form.cleaned_data)
            if overflow and not request.POST.get("confirm_overflow"):
                messages.warning(
                    request,
                    "Avec ces valeurs, des réservations ne tiendraient plus dans leur rangée. "
                    "Vérifiez la liste ci-dessous.",
                )
                overflow_bookings = overflow
            else:
                form.save()
                messages.success(request, "Paramètres enregistrés.")
                return redirect("core:settings")
        else:
            messages.error(
                request, "Les paramètres n'ont pas été enregistrés : corrigez les erreurs."
            )
    else:
        form = AppSettingsForm(instance=app_settings)

    rows = list(Row.objects.all())
    for row in rows:
        row.length = row.effective_length_for(app_settings)
    context = {
        "form": form,
        "app_settings": app_settings,
        "rows": rows,
        "bulk_form": BulkRowCreateForm(),
        "placeholders": REMINDER_PLACEHOLDERS,
        "overflow_bookings": overflow_bookings,
    }
    return render(request, "core/settings.html", context)


def _bookings_overflowing_new_settings(cleaned_data) -> list:
    """Section 6.5: shorter default rows or a bigger gap may leave current or future bookings
    without enough room. They are listed for confirmation; nothing is moved or deleted."""
    saved = AppSettings.load()  # values currently in the database
    new_length = cleaned_data["default_row_length_m"]
    new_gap = cleaned_data["vehicle_gap_m"]
    if new_length >= saved.default_row_length_m and new_gap <= saved.vehicle_gap_m:
        return []
    return services.bookings_not_fitting(default_row_length=new_length, gap=new_gap)


@require_POST
def send_test_email(request):
    """Send a test email to the logged-in user (or the admins) to check the SMTP setup."""
    app_settings = AppSettings.load()
    recipients = [request.user.email] if request.user.email else app_settings.admin_emails
    if not recipients:
        messages.error(
            request,
            "Aucun destinataire : ajoutez une adresse email à votre compte "
            "ou renseignez les emails des administrateurs.",
        )
        return redirect("core:settings")

    try:
        send_mail(
            subject="Email de test – Gestion Stockage Camping-Cars",
            message=(
                "Bonjour,\n\nCet email confirme que l'envoi d'emails fonctionne.\n\n"
                f"Expéditeur utilisé : {app_settings.sender_email}\n"
            ),
            from_email=app_settings.sender_email,
            recipient_list=recipients,
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Test email failed")
        messages.error(request, f"L'envoi a échoué : {exc}")
    else:
        messages.success(request, f"Email de test envoyé à {', '.join(recipients)}.")
    return redirect("core:settings")


@never_cache
def company_logo(request):
    """Serve the uploaded logo. Uploaded files are never public: they go through a login view."""
    logo = AppSettings.load().company_logo
    if not logo:
        raise Http404("Aucun logo")
    try:
        return FileResponse(logo.open("rb"))
    except FileNotFoundError:
        raise Http404("Fichier du logo introuvable") from None
