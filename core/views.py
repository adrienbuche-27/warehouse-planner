import logging
import smtplib

from django.contrib import messages
from django.core.mail import send_mail
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from core.forms import AppSettingsForm, BulkRowCreateForm
from core.models import AppSettings
from core.validators import REMINDER_PLACEHOLDERS
from storage.models import Row

logger = logging.getLogger(__name__)


def dashboard(request):
    """Tableau de bord. KPIs, lists and charts are added in milestone M7."""
    return render(request, "core/dashboard.html")


def settings_page(request):
    """Paramètres: the AppSettings form, the rows table and the test email button."""
    app_settings = AppSettings.load()
    if request.method == "POST":
        form = AppSettingsForm(request.POST, request.FILES, instance=app_settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Paramètres enregistrés.")
            return redirect("core:settings")
        messages.error(request, "Les paramètres n'ont pas été enregistrés : corrigez les erreurs.")
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
    }
    return render(request, "core/settings.html", context)


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
