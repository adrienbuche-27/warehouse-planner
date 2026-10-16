"""Restore a backup made by backup_data. STOP THE APPLICATION FIRST.

    python manage.py restore_backup "C:\\...\\sauvegarde-20270310-190000.zip"

The current data is saved first (avant-restauration-....zip in BACKUP_DIR), so a restore
can be undone by restoring that file.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.backup import BackupError, check_backup, restore_backup


class Command(BaseCommand):
    help = "Restaure une sauvegarde (arrêtez d'abord l'application)."

    def add_arguments(self, parser):
        parser.add_argument("backup_file", help="Path of the sauvegarde-....zip file.")
        parser.add_argument(
            "--oui", action="store_true", help="Do not ask for confirmation (for scripts)."
        )

    def handle(self, *args, backup_file, oui=False, **options):
        path = Path(backup_file)
        try:
            check_backup(path)
        except BackupError as exc:
            raise CommandError(str(exc)) from None

        if not oui:
            self.stdout.write(
                self.style.WARNING(
                    f"Les données actuelles vont être remplacées par celles de {path.name}.\n"
                    "Une copie de sécurité des données actuelles sera faite avant."
                )
            )
            if input("Tapez OUI pour continuer : ").strip() != "OUI":
                raise CommandError("Restauration annulée.")

        try:
            safety = restore_backup(path)
        except BackupError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(f"Données restaurées depuis {path.name}."))
        self.stdout.write(f"Copie de sécurité des données précédentes : {safety.path}")
        self.stdout.write("Vous pouvez redémarrer l'application.")
