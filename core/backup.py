"""Backups of the whole application data: the SQLite database and the uploaded files
(company logo, invoice PDFs). Used by `manage.py backup_data` and `manage.py restore_backup`.

A backup is one zip file, `sauvegarde-AAAAMMJJ-HHMMSS.zip`, containing:
    db.sqlite3      a consistent copy of the database (SQLite online backup, safe while the
                    application is running)
    media/...       the uploaded and generated files
"""

import datetime
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

PREFIX = "sauvegarde-"
SAFETY_PREFIX = "avant-restauration-"
DB_NAME = "db.sqlite3"
MEDIA_DIR = "media"


class BackupError(Exception):
    """A problem the user can fix (message in French)."""


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    deleted: list[Path]


def _copy_database_to(target: Path) -> None:
    """Consistent copy of the live database into `target` (a new SQLite file)."""
    connection.ensure_connection()
    destination = sqlite3.connect(target)
    try:
        connection.connection.backup(destination)
    finally:
        destination.close()


def create_backup(
    directory: Path | None = None, prefix: str = PREFIX, keep_days: int | None = None
) -> BackupResult:
    """Write a new backup zip into `directory` and delete the ones older than `keep_days`."""
    directory = Path(directory or settings.BACKUP_DIR)
    keep_days = settings.BACKUP_KEEP_DAYS if keep_days is None else keep_days
    if not directory.parent.exists():
        raise BackupError(
            f"Le dossier « {directory.parent} » n'existe pas : vérifiez BACKUP_DIR dans .env "
            "(le dossier synchronisé est-il bien installé ?)."
        )
    directory.mkdir(exist_ok=True)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    final_path = directory / f"{prefix}{stamp}.zip"
    counter = 2
    while final_path.exists():  # never overwrite an existing backup (two in the same second)
        final_path = directory / f"{prefix}{stamp}-{counter}.zip"
        counter += 1

    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        _copy_database_to(work / DB_NAME)
        # Build the zip outside the (possibly synced) backup folder, then move it there in one
        # step, so a half-written file is never uploaded.
        temporary_zip = work / final_path.name
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(work / DB_NAME, DB_NAME)
            media_root = Path(settings.MEDIA_ROOT)
            if media_root.exists():
                for file in sorted(media_root.rglob("*")):
                    if file.is_file():
                        archive.write(file, Path(MEDIA_DIR) / file.relative_to(media_root))
        shutil.move(temporary_zip, final_path)

    deleted = delete_old_backups(directory, prefix, keep_days)
    return BackupResult(path=final_path, size_bytes=final_path.stat().st_size, deleted=deleted)


def _backup_date(path: Path, prefix: str) -> datetime.date | None:
    stamp = path.stem[len(prefix) :][:15]  # AAAAMMJJ-HHMMSS, maybe followed by "-2"
    try:
        return datetime.datetime.strptime(stamp, "%Y%m%d-%H%M%S").date()
    except ValueError:
        return None


def delete_old_backups(directory: Path, prefix: str, keep_days: int) -> list[Path]:
    """Delete backups older than `keep_days` days. The most recent one is always kept."""
    backups = sorted(
        (path for path in directory.glob(f"{prefix}*.zip") if _backup_date(path, prefix)),
        key=lambda path: path.name,
    )
    limit = timezone.localdate() - datetime.timedelta(days=keep_days)
    deleted = []
    for path in backups[:-1]:
        if _backup_date(path, prefix) < limit:
            path.unlink()
            deleted.append(path)
    return deleted


def check_backup(path: Path) -> None:
    """Refuse a file that is not a complete, readable backup."""
    if not path.is_file():
        raise BackupError(f"Fichier introuvable : {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            if DB_NAME not in archive.namelist():
                raise BackupError("Ce fichier n'est pas une sauvegarde (db.sqlite3 absent).")
            if archive.testzip() is not None:
                raise BackupError("La sauvegarde est endommagée (fichier zip corrompu).")
    except zipfile.BadZipFile:
        raise BackupError("Ce fichier n'est pas un fichier zip valide.") from None


def restore_backup(path: Path) -> BackupResult:
    """Replace the current data with the backup at `path`.

    A safety backup of the current data is made first (prefix "avant-restauration-"), so a
    restore can itself be undone. Stop the application before restoring.
    """
    path = Path(path)
    check_backup(path)
    safety = create_backup(prefix=SAFETY_PREFIX)

    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(work)
        restored_db = sqlite3.connect(work / DB_NAME)
        try:
            if restored_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("La base de données de la sauvegarde est endommagée.")
            connection.ensure_connection()
            restored_db.backup(connection.connection)
        finally:
            restored_db.close()

        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            shutil.rmtree(media_root)
        if (work / MEDIA_DIR).exists():
            shutil.copytree(work / MEDIA_DIR, media_root)
    return safety
