"""M8: backup and restore of the database and the uploaded files."""

import datetime
import zipfile
from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from clients.models import Client
from core import backup
from tests.factories import make_client

# The restore writes into the live database: it cannot run inside the usual test transaction.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def folders(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.BACKUP_DIR = tmp_path / "cloud" / "Sauvegardes Stockage"
    (tmp_path / "cloud").mkdir()
    (tmp_path / "media" / "invoices" / "2027").mkdir(parents=True)
    (tmp_path / "media" / "invoices" / "2027" / "2027-0001.pdf").write_bytes(b"%PDF-1.7 test")
    return tmp_path


def test_backup_contains_database_and_files(folders):
    make_client(last_name="Sauvegardé")
    result = backup.create_backup()
    assert result.path.parent == folders / "cloud" / "Sauvegardes Stockage"
    assert result.path.name.startswith("sauvegarde-") and result.path.suffix == ".zip"
    with zipfile.ZipFile(result.path) as archive:
        names = archive.namelist()
        assert "db.sqlite3" in names
        assert "media/invoices/2027/2027-0001.pdf" in names
        assert archive.read("media/invoices/2027/2027-0001.pdf") == b"%PDF-1.7 test"


def test_backup_refuses_a_missing_cloud_folder(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path / "pas-installé" / "Sauvegardes"
    with pytest.raises(backup.BackupError, match="BACKUP_DIR"):
        backup.create_backup()


def test_old_backups_are_deleted_but_the_last_one_is_kept(folders):
    directory = folders / "cloud" / "Sauvegardes Stockage"
    directory.mkdir()
    old = directory / "sauvegarde-20200101-190000.zip"
    old.write_bytes(b"x")
    other_file = directory / "notes.txt"
    other_file.write_text("pas une sauvegarde")
    result = backup.create_backup(keep_days=30)
    assert result.deleted == [old]
    assert not old.exists() and other_file.exists() and result.path.exists()

    assert backup.delete_old_backups(directory, "sauvegarde-", keep_days=0) == []  # last kept


def test_restore_brings_back_data_and_files_and_keeps_a_safety_copy(folders):
    make_client(last_name="Avant")
    saved = backup.create_backup()
    Client.objects.all().delete()
    make_client(last_name="Après")
    (folders / "media" / "invoices" / "2027" / "2027-0001.pdf").unlink()

    safety = backup.restore_backup(saved.path)

    assert list(Client.objects.values_list("last_name", flat=True)) == ["Avant"]
    assert (
        folders / "media" / "invoices" / "2027" / "2027-0001.pdf"
    ).read_bytes() == b"%PDF-1.7 test"
    assert safety.path.name.startswith("avant-restauration-")
    # The safety copy holds the data as it was just before the restore.
    backup.restore_backup(safety.path)
    assert list(Client.objects.values_list("last_name", flat=True)) == ["Après"]


def test_restore_refuses_files_that_are_not_backups(folders):
    not_zip = folders / "facture.pdf"
    not_zip.write_bytes(b"%PDF")
    with pytest.raises(backup.BackupError, match="zip"):
        backup.restore_backup(not_zip)
    wrong_zip = folders / "photos.zip"
    with zipfile.ZipFile(wrong_zip, "w") as archive:
        archive.writestr("photo.jpg", b"x")
    with pytest.raises(backup.BackupError, match="db.sqlite3"):
        backup.restore_backup(wrong_zip)
    with pytest.raises(backup.BackupError, match="introuvable"):
        backup.restore_backup(folders / "absent.zip")


def test_backup_command(folders):
    out = StringIO()
    call_command("backup_data", stdout=out)
    assert "Sauvegarde créée" in out.getvalue()


def test_restore_command_asks_for_confirmation(folders):
    make_client(last_name="Avant")
    saved = backup.create_backup()
    make_client(last_name="Nouveau")
    with (
        mock.patch("builtins.input", return_value="non"),
        pytest.raises(CommandError, match="annulée"),
    ):
        call_command("restore_backup", str(saved.path), stdout=StringIO())
    assert Client.objects.count() == 2

    out = StringIO()
    call_command("restore_backup", str(saved.path), "--oui", stdout=out)
    assert "Données restaurées" in out.getvalue()
    assert Client.objects.count() == 1


def test_backup_date_is_read_from_the_file_name():
    from pathlib import Path

    assert backup._backup_date(
        Path("sauvegarde-20270310-190000.zip"), "sauvegarde-"
    ) == datetime.date(2027, 3, 10)
    assert backup._backup_date(Path("sauvegarde-copie.zip"), "sauvegarde-") is None


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(folders):
    first = backup.create_backup()
    second = backup.create_backup()
    assert first.path != second.path
    assert first.path.exists() and second.path.exists()
