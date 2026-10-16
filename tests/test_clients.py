"""M2: clients and vehicles (models, search, screens, archive, delete)."""

from decimal import Decimal
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from clients.models import Client, ClientType, Vehicle
from clients.services import search_clients, search_vehicles
from tests.factories import make_business, make_client, make_vehicle

pytestmark = pytest.mark.django_db


# --- Client model ------------------------------------------------------------


def test_private_client_requires_first_and_last_name():
    client = Client(client_type=ClientType.PRIVATE, email="a@example.be")
    with pytest.raises(ValidationError) as exc:
        client.full_clean()
    assert {"first_name", "last_name"} <= set(exc.value.message_dict)
    assert "company_name" not in exc.value.message_dict


def test_business_client_requires_company_name_and_vat_number():
    client = Client(client_type=ClientType.BUSINESS, email="a@example.be")
    with pytest.raises(ValidationError) as exc:
        client.full_clean()
    assert {"company_name", "vat_number"} <= set(exc.value.message_dict)
    assert "first_name" not in exc.value.message_dict


def test_email_is_required():
    client = Client(first_name="Jean", last_name="Dupont")
    with pytest.raises(ValidationError) as exc:
        client.full_clean()
    assert "email" in exc.value.message_dict


def test_business_vat_number_is_validated_and_normalised():
    client = Client(
        client_type=ClientType.BUSINESS,
        company_name="Évasion SRL",
        vat_number="BE123",
        email="a@example.be",
    )
    with pytest.raises(ValidationError) as exc:
        client.full_clean()
    assert "vat_number" in exc.value.message_dict

    client.vat_number = "be 0123.456.789"
    client.full_clean()
    client.save()
    assert Client.objects.get(pk=client.pk).vat_number == "BE0123456789"


def test_display_name_and_address():
    private = make_client(
        first_name="Marie",
        last_name="Lambert",
        street="Rue Haute 5",
        postal_code="6700",
        city="Arlon",
    )
    business = make_business(
        company_name="Évasion SRL", country="Luxembourg", postal_code="L-1234", city="Luxembourg"
    )
    assert private.display_name == "Marie Lambert"
    assert business.display_name == "Évasion SRL"
    assert private.address_lines == ["Rue Haute 5", "6700 Arlon"]
    assert business.address_lines == ["L-1234 Luxembourg", "Luxembourg"]
    assert Client().country == "Belgique"


def test_clients_are_sorted_by_displayed_name():
    make_client(first_name="Paul", last_name="Martin")
    make_business(company_name="Bruyère SRL")
    make_client(first_name="Anne", last_name="Adam")
    assert [c.display_name for c in Client.objects.all()] == [
        "Anne Adam",
        "Bruyère SRL",
        "Paul Martin",
    ]


# --- Vehicle model -----------------------------------------------------------


def test_plate_is_stored_uppercase_without_spaces():
    vehicle = make_vehicle(plate=" 1-abc 123 ")
    assert vehicle.plate == "1-ABC123"


def test_plate_must_be_unique_even_with_different_spelling(admin_client):
    owner = make_client()
    make_vehicle(client=owner, plate="1-ABC-123")
    data = {"client": owner.pk, "plate": "1-abc-123 ", "length_m": "7"}
    response = admin_client.post(reverse("clients:vehicle_create"), data)
    assert response.status_code == 200
    assert "Un véhicule avec cette plaque existe déjà." in response.content.decode()
    assert Vehicle.objects.count() == 1


@pytest.mark.parametrize("length", ["0", "-1", "25"])
def test_vehicle_length_must_be_positive_and_plausible(length):
    vehicle = Vehicle(client=make_client(), plate="X", length_m=Decimal(length))
    with pytest.raises(ValidationError) as exc:
        vehicle.full_clean()
    assert "length_m" in exc.value.message_dict


def test_vehicle_of_archived_client_counts_as_archived():
    owner = make_client()
    vehicle = make_vehicle(client=owner)
    assert list(Vehicle.objects.active()) == [vehicle]
    owner.is_archived = True
    owner.save()
    vehicle.refresh_from_db()
    assert vehicle.is_effectively_archived
    assert list(Vehicle.objects.active()) == []
    assert list(Vehicle.objects.archived()) == [vehicle]


# --- Search ------------------------------------------------------------------


def test_search_clients_by_words_across_fields():
    jean = make_client(first_name="Jean", last_name="Dupont", city="Arlon")
    make_client(first_name="Jean", last_name="Martin", city="Bastogne")
    assert list(search_clients("jean dupont")) == [jean]
    assert list(search_clients("dupont arlon")) == [jean]
    assert search_clients("jean").count() == 2


def test_search_clients_by_vehicle_plate_without_duplicates():
    owner = make_client()
    make_vehicle(client=owner, plate="1-ABC-123")
    make_vehicle(client=owner, plate="1-ABC-456")
    assert list(search_clients("1-abc")) == [owner]


def test_search_clients_filters_type_and_archived():
    private = make_client()
    business = make_business()
    archived = make_client(is_archived=True)
    assert set(search_clients()) == {private, business}
    assert list(search_clients(client_type=ClientType.BUSINESS)) == [business]
    assert archived in search_clients(include_archived=True)


def test_search_vehicles():
    owner = make_client(last_name="Lambert")
    vehicle = make_vehicle(client=owner, plate="2-XYZ-999", brand="Hymer")
    make_vehicle(brand="Fiat")
    assert list(search_vehicles("hymer")) == [vehicle]
    assert list(search_vehicles("lambert 2-xyz")) == [vehicle]
    archived = make_vehicle(is_archived=True)
    assert archived not in search_vehicles()
    assert archived in search_vehicles(include_archived=True)


# --- Client screens ----------------------------------------------------------


def test_client_pages_require_login(client):
    assert client.get(reverse("clients:client_list")).status_code == 302
    assert client.get(reverse("clients:vehicle_list")).status_code == 302


def test_client_list_search_and_live_results(admin_client):
    make_client(first_name="Marie", last_name="Lambert")
    make_client(first_name="Paul", last_name="Martin")
    response = admin_client.get(reverse("clients:client_list"), {"q": "lambert"})
    content = response.content.decode()
    assert "Marie Lambert" in content and "Paul Martin" not in content
    assert 'aria-current="page">Clients' in content

    # HTMX request: only the results fragment, without the page layout.
    response = admin_client.get(
        reverse("clients:client_list"), {"q": "martin"}, headers={"HX-Request": "true"}
    )
    content = response.content.decode()
    assert "Paul Martin" in content
    assert "<html" not in content


def test_client_list_hides_archived_unless_asked(admin_client):
    make_client(first_name="Ancien", last_name="Client", is_archived=True)
    url = reverse("clients:client_list")
    assert "Ancien Client" not in admin_client.get(url).content.decode()
    assert "Ancien Client" in admin_client.get(url, {"archives": "1"}).content.decode()


def test_client_list_is_paginated(admin_client):
    for _ in range(55):
        make_client()
    response = admin_client.get(reverse("clients:client_list"))
    assert len(response.context["page"].object_list) == 50
    assert "Page 1 / 2" in response.content.decode()


def test_create_private_client(admin_client):
    data = {
        "client_type": "private",
        "first_name": "Marie",
        "last_name": "Lambert",
        "email": "marie@example.be",
        "country": "Belgique",
    }
    response = admin_client.post(reverse("clients:client_create"), data)
    client = Client.objects.get()
    assert response.url == reverse("clients:client_detail", args=[client.pk])
    assert client.display_name == "Marie Lambert"


def test_create_business_client_shows_french_errors(admin_client):
    data = {"client_type": "business", "email": "info@example.be", "country": "Belgique"}
    response = admin_client.post(reverse("clients:client_create"), data)
    content = response.content.decode()
    assert "Le nom de l&#x27;entreprise est obligatoire." in content
    assert "Le numéro de TVA est obligatoire pour une entreprise." in content
    assert Client.objects.count() == 0


def test_edit_client(admin_client):
    client = make_client(first_name="Marie", last_name="Lambert")
    data = {
        "client_type": "private",
        "first_name": "Marie",
        "last_name": "Lambert-Dubois",
        "email": client.email,
        "country": "Belgique",
    }
    admin_client.post(reverse("clients:client_edit", args=[client.pk]), data)
    client.refresh_from_db()
    assert client.last_name == "Lambert-Dubois"


def test_client_detail_lists_vehicles(admin_client):
    client = make_client()
    make_vehicle(client=client, plate="1-ABC-123", length_m=Decimal("7.5"))
    content = admin_client.get(reverse("clients:client_detail", args=[client.pk])).content.decode()
    assert "1-ABC-123" in content
    assert "7,50 m" in content
    assert f"?client={client.pk}" in content


def test_archive_and_restore_client(admin_client):
    client = make_client()
    url = reverse("clients:client_archive", args=[client.pk])
    admin_client.post(url)
    client.refresh_from_db()
    assert client.is_archived
    admin_client.post(url)
    client.refresh_from_db()
    assert not client.is_archived
    assert admin_client.get(url).status_code == 405


def test_delete_client_also_deletes_its_vehicles(admin_client):
    client = make_client()
    make_vehicle(client=client, plate="1-ABC-123")
    url = reverse("clients:client_delete", args=[client.pk])
    content = admin_client.get(url).content.decode()
    assert "Supprimer définitivement" in content and "1-ABC-123" in content
    response = admin_client.post(url)
    assert response.url == reverse("clients:client_list")
    assert Client.objects.count() == 0
    assert Vehicle.objects.count() == 0


def test_delete_client_refused_when_linked_records_exist(admin_client):
    # Bookings (M3) and invoices (M5) protect clients and vehicles from deletion.
    client = make_client()
    url = reverse("clients:client_delete", args=[client.pk])
    with mock.patch("clients.views.protected_objects", return_value=["booking"]):
        content = admin_client.get(url).content.decode()
        assert "ne peut pas être supprimé" in content
        assert "Archiver le client" in content
        assert "Supprimer définitivement" not in content
        admin_client.post(url)
    assert Client.objects.filter(pk=client.pk).exists()


# --- Vehicle screens ---------------------------------------------------------


def test_vehicle_create_prefills_client_and_hides_archived_clients(admin_client):
    owner = make_client(first_name="Marie", last_name="Lambert")
    make_client(first_name="Ancien", last_name="Client", is_archived=True)
    response = admin_client.get(reverse("clients:vehicle_create"), {"client": owner.pk})
    form = response.context["form"]
    assert str(form.initial["client"]) == str(owner.pk)
    assert list(form.fields["client"].queryset) == [owner]


def test_create_and_edit_vehicle(admin_client):
    owner = make_client()
    data = {"client": owner.pk, "plate": "1-abc-123", "brand": "Hymer", "length_m": "7.40"}
    response = admin_client.post(reverse("clients:vehicle_create"), data)
    vehicle = Vehicle.objects.get()
    assert response.url == reverse("clients:vehicle_detail", args=[vehicle.pk])
    assert vehicle.plate == "1-ABC-123"
    assert vehicle.length_m == Decimal("7.40")

    data.update({"height_m": "3.10", "model": "B-Klasse"})
    admin_client.post(reverse("clients:vehicle_edit", args=[vehicle.pk]), data)
    vehicle.refresh_from_db()
    assert vehicle.height_m == Decimal("3.10")
    content = admin_client.get(
        reverse("clients:vehicle_detail", args=[vehicle.pk])
    ).content.decode()
    assert "Hymer B-Klasse" in content and "3,10 m" in content


def test_editing_vehicle_of_archived_client_keeps_its_owner(admin_client):
    owner = make_client(is_archived=True)
    vehicle = make_vehicle(client=owner)
    response = admin_client.get(reverse("clients:vehicle_edit", args=[vehicle.pk]))
    assert owner in response.context["form"].fields["client"].queryset


def test_vehicle_list_search_and_archived(admin_client):
    make_vehicle(plate="1-ABC-123", brand="Hymer")
    make_vehicle(plate="9-OLD-999", is_archived=True)
    url = reverse("clients:vehicle_list")
    content = admin_client.get(url, {"q": "hymer"}).content.decode()
    assert "1-ABC-123" in content
    assert "9-OLD-999" not in admin_client.get(url).content.decode()
    assert "9-OLD-999" in admin_client.get(url, {"archives": "1"}).content.decode()


def test_archive_and_delete_vehicle(admin_client):
    owner = make_client()
    vehicle = make_vehicle(client=owner)
    admin_client.post(reverse("clients:vehicle_archive", args=[vehicle.pk]))
    vehicle.refresh_from_db()
    assert vehicle.is_archived

    response = admin_client.post(reverse("clients:vehicle_delete", args=[vehicle.pk]))
    assert response.url == reverse("clients:client_detail", args=[owner.pk])
    assert not Vehicle.objects.exists()
    assert Client.objects.filter(pk=owner.pk).exists()
