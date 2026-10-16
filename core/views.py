from django.shortcuts import render


def dashboard(request):
    """Tableau de bord. KPIs, lists and charts are added in milestone M7."""
    return render(request, "core/dashboard.html")
