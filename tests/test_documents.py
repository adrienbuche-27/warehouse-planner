"""Document checks on each booking (backlog V3-1): ID and insurance, status only."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from storage import services
from storage.models import Booking, BookingStatus, DocumentStatus
from tests.factories import make_booking, make_row, make_vehicle

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def booking_starting_in(days, **fields):
    return make_booking(make_row(), 1, TODAY + datetime.timedelta(days=days), **fields)


def check(booking, slug, status, user=None, note=""):
    services.set_document_status(booking, slug, status, user, note)
    booking.refresh_from_db()


# --- Model and service -----------------------------------------------------------


def test_a_new_booking_has_both_documents_missing():
    booking = booking_starting_in(3)
    assert [(d.label, d.status) for d in booking.documents] == [
        ("Pièce d'identité", DocumentStatus.MISSING),
        ("Assurance", DocumentStatus.MISSING),
    ]
    assert not booking.documents_complete


def test_checking_a_document_records_who_when_and_why(admin_user):
    booking = booking_starting_in(3)
    check(booking, "assurance", DocumentStatus.INVALID, admin_user, "  Attestation expirée  ")
    insurance = booking.document("assurance")
    assert insurance.status == DocumentStatus.INVALID and insurance.status_label == "Invalide"
    assert insurance.checked_by == admin_user
    assert timezone.now() - insurance.checked_at < datetime.timedelta(minutes=1)
    assert insurance.note == "Attestation expirée"
    assert booking.document("identite").status == DocumentStatus.MISSING  # untouched


def test_documents_complete_only_when_both_are_valid(admin_user):
    booking = booking_starting_in(3)
    check(booking, "identite", DocumentStatus.VALID, admin_user)
    assert not booking.documents_complete
    assert list(Booking.objects.documents_incomplete()) == [booking]
    check(booking, "assurance", DocumentStatus.VALID, admin_user)
    assert booking.documents_complete
    assert not Booking.objects.documents_incomplete().exists()


def test_each_booking_is_checked_again_even_for_the_same_vehicle(admin_user):
    vehicle = make_vehicle()
    first = make_booking(make_row(), 1, TODAY, vehicle=vehicle)
    check(first, "identite", DocumentStatus.VALID, admin_user)
    check(first, "assurance", DocumentStatus.VALID, admin_user)
    later = make_booking(make_row(), 1, TODAY + datetime.timedelta(days=60), vehicle=vehicle)
    assert not later.documents_complete  # nothing copied from the earlier booking


def test_unknown_document_or_status_is_refused(admin_user):
    booking = booking_starting_in(3)
    with pytest.raises(services.BookingActionError):
        services.set_document_status(booking, "permis", DocumentStatus.VALID, admin_user)
    with pytest.raises(services.BookingActionError):
        services.set_document_status(booking, "identite", "ok", admin_user)


def test_user_deletion_keeps_the_check(django_user_model):
    user = django_user_model.objects.create_user("marie", password="x")
    booking = booking_starting_in(3)
    check(booking, "identite", DocumentStatus.VALID, user)
    user.delete()
    booking.refresh_from_db()
    assert booking.id_status == DocumentStatus.VALID and booking.id_checked_by is None


# --- Booking detail ------------------------------------------------------------------


def test_booking_detail_shows_the_documents(admin_client):
    booking = booking_starting_in(3)
    content = admin_client.get(
        reverse("storage:booking_detail", args=[booking.pk])
    ).content.decode()
    assert 'id="documents"' in content and "Documents à compléter" in content
    assert "Pas encore vérifié" in content
    for slug in ("identite", "assurance"):
        assert reverse("storage:booking_document", args=[booking.pk, slug]) in content


def test_one_click_records_the_check(admin_client, admin_user):
    booking = booking_starting_in(3)
    url = reverse("storage:booking_document", args=[booking.pk, "identite"])
    response = admin_client.post(url, {"status": "valid", "note": ""}, follow=True)
    assert response.redirect_chain[-1][0].endswith("#documents")
    content = response.content.decode()
    assert "Pièce d&#x27;identité : valide." in content
    assert f"par {admin_user.username}" in content
    booking.refresh_from_db()
    assert booking.id_status == DocumentStatus.VALID and booking.id_checked_by == admin_user

    url = reverse("storage:booking_document", args=[booking.pk, "assurance"])
    admin_client.post(url, {"status": "invalid", "note": "Nom différent"})
    content = admin_client.get(
        reverse("storage:booking_detail", args=[booking.pk])
    ).content.decode()
    assert "Remarque : Nom différent" in content and "Invalide" in content


def test_document_view_refuses_bad_requests(admin_client):
    booking = booking_starting_in(3)
    url = reverse("storage:booking_document", args=[booking.pk, "identite"])
    assert admin_client.get(url).status_code == 405
    bad = reverse("storage:booking_document", args=[booking.pk, "permis"])
    assert admin_client.post(bad, {"status": "valid"}).status_code == 404
    response = admin_client.post(url, {"status": "ok"}, follow=True)
    assert "Statut de document inconnu." in response.content.decode()


def test_document_view_requires_login(client):
    booking = booking_starting_in(3)
    url = reverse("storage:booking_document", args=[booking.pk, "identite"])
    assert client.post(url, {"status": "valid"}).status_code == 302
    booking.refresh_from_db()
    assert booking.id_status == DocumentStatus.MISSING


# --- Bookings list and dashboard -----------------------------------------------------


def test_bookings_list_shows_icons_and_filters_incomplete_documents(admin_client, admin_user):
    done = booking_starting_in(3, vehicle=make_vehicle(plate="DONE-1"))
    check(done, "identite", DocumentStatus.VALID, admin_user)
    check(done, "assurance", DocumentStatus.VALID, admin_user)
    booking_starting_in(5, vehicle=make_vehicle(plate="TODO-1"))
    url = reverse("storage:booking_list")
    content = admin_client.get(url).content.decode()
    assert 'class="doc-mini doc-valid" title="Pièce d&#x27;identité : valide"' in content
    assert "Documents à compléter" in content  # the filter
    response = admin_client.get(url, {"documents": "a-completer"})
    plates = [b.vehicle.plate for b in response.context["page"].object_list]
    assert plates == ["TODO-1"]


def test_dashboard_lists_documents_to_complete(admin_client, admin_user):
    stored = booking_starting_in(
        -10, status=BookingStatus.STORED, vehicle=make_vehicle(plate="IN-1")
    )
    soon = booking_starting_in(5, vehicle=make_vehicle(plate="SOON-1"))
    booking_starting_in(40, vehicle=make_vehicle(plate="LATER-1"))  # beyond 14 days
    booking_starting_in(2, status=BookingStatus.CANCELLED, vehicle=make_vehicle(plate="CXL-1"))
    complete = booking_starting_in(1, vehicle=make_vehicle(plate="OK-1"))
    for slug in ("identite", "assurance"):
        check(complete, slug, DocumentStatus.VALID, admin_user)

    response = admin_client.get(reverse("core:dashboard"))
    assert response.context["documents_to_complete"] == [stored, soon]
    content = response.content.decode()
    assert "Documents à compléter" in content
    assert f"{reverse('storage:booking_list')}?documents=a-completer" in content


def test_dashboard_when_all_documents_are_checked(admin_client):
    content = admin_client.get(reverse("core:dashboard")).content.decode()
    assert "Tous les documents des véhicules en stock" in content
