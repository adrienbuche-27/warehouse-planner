"""Back up the database and the uploaded files into BACKUP_DIR (see .env).

    python manage.py backup_data

Run every day by the scheduled task "Stockage - sauvegarde" (deploy/windows/).
Keeps BACKUP_KEEP_DAYS days of backups (30 by default).
"""

from django.core.management.base import BaseCommand, CommandError

from core.backup import BackupError, create_backup


class Command(BaseCommand):
    help = "Sauvegarde la base de données et les fichiers (logo, factures PDF)."

    def handle(self, *args, **options):
        try:
            result = create_backup()
        except BackupError as exc:
            raise CommandError(str(exc)) from None
        size = result.size_bytes / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Sauvegarde créée : {result.path} ({size:.1f} Mo)."))
        for path in result.deleted:
            self.stdout.write(f"Ancienne sauvegarde supprimée : {path.name}")
