from django.urls import path

from invoicing import views

app_name = "invoicing"

urlpatterns = [
    path("factures/", views.invoice_list, name="invoice_list"),
    path("factures/nouvelle/", views.invoice_create, name="invoice_create"),
    path(
        "factures/reservation/<int:booking_pk>/",
        views.invoice_from_booking,
        name="invoice_from_booking",
    ),
    path("factures/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("factures/<int:pk>/modifier/", views.invoice_edit, name="invoice_edit"),
    path("factures/<int:pk>/emettre/", views.invoice_issue, name="invoice_issue"),
    path("factures/<int:pk>/supprimer/", views.invoice_delete, name="invoice_delete"),
    path("factures/<int:pk>/payer/", views.invoice_pay, name="invoice_pay"),
    path("factures/<int:pk>/annuler-paiement/", views.invoice_unpay, name="invoice_unpay"),
    path("factures/<int:pk>/note-de-credit/", views.credit_note_create, name="credit_note_create"),
    path("notes-de-credit/", views.credit_note_list, name="credit_note_list"),
    path("notes-de-credit/<int:pk>/", views.credit_note_detail, name="credit_note_detail"),
    path("notes-de-credit/<int:pk>/modifier/", views.credit_note_edit, name="credit_note_edit"),
    path("notes-de-credit/<int:pk>/emettre/", views.credit_note_issue, name="credit_note_issue"),
    path(
        "notes-de-credit/<int:pk>/supprimer/",
        views.credit_note_delete,
        name="credit_note_delete",
    ),
    path("documents/<str:kind>/<int:pk>/pdf/", views.document_pdf, name="document_pdf"),
    path("documents/<str:kind>/<int:pk>/envoyer/", views.document_email, name="document_email"),
]
