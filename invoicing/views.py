import logging
import smtplib

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from clients.models import Client
from invoicing import services
from invoicing.forms import (
    CreditNoteLineFormSet,
    CreditNoteReasonForm,
    InvoiceLineFormSet,
    ManualInvoiceForm,
    PaymentForm,
)
from invoicing.models import CreditNote, Invoice, InvoiceStatus
from storage.models import Booking

logger = logging.getLogger(__name__)
PAGE_SIZE = 50


def _parse_date(value):
    try:
        return parse_date(value or "")
    except ValueError:  # well formatted but impossible, e.g. 2027-02-30
        return None


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


# --- Invoices ------------------------------------------------------------------


def invoice_list(request):
    status = request.GET.get("statut", "")
    client_id = request.GET.get("client", "")
    date_from = _parse_date(request.GET.get("du"))
    date_to = _parse_date(request.GET.get("au"))
    overdue_only = request.GET.get("retard") == "1"
    query = request.GET.get("q", "").strip()

    invoices = Invoice.objects.select_related("client")
    if status in InvoiceStatus.values:
        invoices = invoices.filter(status=status)
    if client_id.isdigit():
        invoices = invoices.filter(client_id=client_id)
    if date_from:
        invoices = invoices.filter(issue_date__gte=date_from)
    if date_to:
        invoices = invoices.filter(issue_date__lte=date_to)
    if overdue_only:
        invoices = invoices.filter(status=InvoiceStatus.ISSUED, due_date__lt=services.today())
    for word in query.split():
        invoices = invoices.filter(
            Q(number__icontains=word)
            | Q(client_name__icontains=word)
            | Q(client__last_name__icontains=word)
            | Q(client__company_name__icontains=word)
        )

    totals = invoices.aggregate(
        excl=Sum("total_excl_vat"), vat=Sum("total_vat"), incl=Sum("total_incl_vat")
    )
    page = Paginator(invoices, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "totals": totals,
        "status": status,
        "statuses": InvoiceStatus.choices,
        "client_id": client_id,
        "clients": Client.objects.filter(invoice__isnull=False).distinct(),
        "date_from": date_from,
        "date_to": date_to,
        "overdue_only": overdue_only,
        "query": query,
    }
    template = (
        "invoicing/_invoice_results.html" if _is_htmx(request) else "invoicing/invoice_list.html"
    )
    return render(request, template, context)


def invoice_create(request):
    """Manual invoice (not linked to a booking): choose the client, then add lines."""
    form = ManualInvoiceForm(request.POST or None, initial={"client": request.GET.get("client")})
    if form.is_valid():
        invoice = services.create_manual_invoice(form.cleaned_data["client"])
        messages.success(request, "Brouillon créé : ajoutez les lignes de la facture.")
        return redirect("invoicing:invoice_edit", pk=invoice.pk)
    return render(request, "invoicing/invoice_create.html", {"form": form})


@require_POST
def invoice_from_booking(request, booking_pk):
    """ "Créer la facture" on a booking: a draft for its periods not invoiced yet."""
    booking = get_object_or_404(Booking.objects.select_related("vehicle__client"), pk=booking_pk)
    try:
        invoice = services.create_invoice_for_booking(booking)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
        return redirect("storage:booking_detail", pk=booking.pk)
    messages.success(
        request, "Brouillon de facture créé. Vérifiez-le puis cliquez sur « Émettre »."
    )
    return redirect("invoicing:invoice_detail", pk=invoice.pk)


def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "booking__vehicle", "booking__row"), pk=pk
    )
    context = {
        "doc": invoice,
        "lines": invoice.lines.all(),
        "credit_notes": invoice.credit_notes.all(),
        "remaining_to_credit": services.remaining_to_credit(invoice),
        "payment_form": PaymentForm(),
        "credit_form": CreditNoteReasonForm(),
        "missing_company": services.missing_company_details_now(),
        "missing_client": services.missing_client_details(invoice.client),
    }
    return render(request, "invoicing/invoice_detail.html", context)


def _edit_lines(request, document, formset_class, template, detail_url_name, extra_form=None):
    """Edit the lines (and the reason, for a credit note) of a draft."""
    if not document.is_draft:
        messages.error(request, "Un document émis ne peut plus être modifié.")
        return redirect(detail_url_name, pk=document.pk)
    formset = formset_class(request.POST or None, instance=document)
    if (
        request.method == "POST"
        and formset.is_valid()
        and (extra_form is None or extra_form.is_valid())
    ):
        with transaction.atomic():
            if extra_form is not None:
                extra_form.save()
            formset.save()
            services.recalculate_totals(document)
            document.save()
        messages.success(request, "Brouillon enregistré.")
        return redirect(detail_url_name, pk=document.pk)
    context = {"doc": document, "formset": formset, "extra_form": extra_form}
    return render(request, template, context)


def invoice_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    return _edit_lines(
        request,
        invoice,
        InvoiceLineFormSet,
        "invoicing/document_edit.html",
        "invoicing:invoice_detail",
    )


@require_POST
def invoice_issue(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        services.issue_invoice(invoice)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Facture {invoice.number} émise. Le PDF est prêt.")
    return redirect("invoicing:invoice_detail", pk=invoice.pk)


@require_POST
def invoice_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    booking = invoice.booking
    try:
        services.delete_draft(invoice)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
        return redirect("invoicing:invoice_detail", pk=pk)
    messages.success(request, "Brouillon supprimé.")
    if booking:
        return redirect("storage:booking_detail", pk=booking.pk)
    return redirect("invoicing:invoice_list")


@require_POST
def invoice_pay(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Date ou mode de paiement invalide.")
        return redirect("invoicing:invoice_detail", pk=pk)
    try:
        services.mark_paid(
            invoice,
            form.cleaned_data["paid_on"],
            form.cleaned_data["payment_method"],
            form.cleaned_data["payment_note"],
        )
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Facture {invoice.number} marquée payée.")
    return redirect("invoicing:invoice_detail", pk=pk)


@require_POST
def invoice_unpay(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        services.cancel_payment(invoice)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Paiement annulé : la facture est de nouveau à payer.")
    return redirect("invoicing:invoice_detail", pk=pk)


@require_POST
def credit_note_create(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = CreditNoteReasonForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indiquez le motif de la note de crédit.")
        return redirect("invoicing:invoice_detail", pk=pk)
    try:
        credit_note = services.create_credit_note(invoice, form.cleaned_data["reason"])
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
        return redirect("invoicing:invoice_detail", pk=pk)
    messages.success(
        request,
        "Brouillon de note de crédit créé pour le montant total. Modifiez les lignes pour "
        "ne créditer qu'une partie, puis émettez-la.",
    )
    return redirect("invoicing:credit_note_detail", pk=credit_note.pk)


# --- Credit notes --------------------------------------------------------------


def credit_note_list(request):
    credit_notes = CreditNote.objects.select_related("invoice", "client")
    page = Paginator(credit_notes, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "invoicing/credit_note_list.html", {"page": page})


def credit_note_detail(request, pk):
    credit_note = get_object_or_404(CreditNote.objects.select_related("invoice", "client"), pk=pk)
    context = {
        "doc": credit_note,
        "lines": credit_note.lines.all(),
        "remaining_to_credit": services.remaining_to_credit(credit_note.invoice),
        "missing_company": services.missing_company_details_now(),
    }
    return render(request, "invoicing/credit_note_detail.html", context)


def credit_note_edit(request, pk):
    credit_note = get_object_or_404(CreditNote, pk=pk)
    reason_form = CreditNoteReasonForm(request.POST or None, instance=credit_note)
    return _edit_lines(
        request,
        credit_note,
        CreditNoteLineFormSet,
        "invoicing/document_edit.html",
        "invoicing:credit_note_detail",
        extra_form=reason_form,
    )


@require_POST
def credit_note_issue(request, pk):
    credit_note = get_object_or_404(CreditNote, pk=pk)
    try:
        services.issue_credit_note(credit_note)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
    else:
        message = f"Note de crédit {credit_note.number} émise."
        if credit_note.invoice.status == InvoiceStatus.CANCELLED:
            message += f" La facture {credit_note.invoice.number} est annulée."
        messages.success(request, message)
    return redirect("invoicing:credit_note_detail", pk=pk)


@require_POST
def credit_note_delete(request, pk):
    credit_note = get_object_or_404(CreditNote, pk=pk)
    invoice_pk = credit_note.invoice_id
    try:
        services.delete_draft(credit_note)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
        return redirect("invoicing:credit_note_detail", pk=pk)
    messages.success(request, "Brouillon de note de crédit supprimé.")
    return redirect("invoicing:invoice_detail", pk=invoice_pk)


# --- PDF and email (both kinds) --------------------------------------------------

DOCUMENT_MODELS = {"facture": Invoice, "note-de-credit": CreditNote}


def _document(kind, pk):
    model = DOCUMENT_MODELS.get(kind)
    if model is None:
        raise Http404
    return get_object_or_404(model, pk=pk)


def document_pdf(request, kind, pk):
    """The stored PDF, served as is (never regenerated). Only for logged-in users."""
    document = _document(kind, pk)
    if not document.pdf_file:
        raise Http404("Pas de PDF pour un brouillon")
    try:
        pdf = document.pdf_file.open("rb")
    except FileNotFoundError:
        raise Http404("Fichier PDF introuvable") from None
    return FileResponse(pdf, content_type="application/pdf", filename=f"{document.number}.pdf")


@require_POST
def document_email(request, kind, pk):
    document = _document(kind, pk)
    detail = "invoicing:invoice_detail" if kind == "facture" else "invoicing:credit_note_detail"
    try:
        recipient = services.email_document(document)
    except services.InvoicingError as exc:
        messages.error(request, str(exc))
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Sending %s %s failed", kind, document.number)
        messages.error(request, f"L'envoi a échoué : {exc}")
    else:
        messages.success(request, f"{document.number} envoyé à {recipient}.")
    return redirect(detail, pk=pk)
