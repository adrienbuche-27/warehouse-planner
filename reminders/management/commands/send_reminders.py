"""Send the end-of-storage reminders. Run once a day (systemd timer or cron, 08:00).

    python manage.py send_reminders            # send what is due
    python manage.py send_reminders --dry-run  # only show what would be sent

Safe to run several times: a reminder already sent is never sent again.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError

from reminders.services import send_reminders


class Command(BaseCommand):
    help = "Envoie les rappels de fin de stockage (à lancer une fois par jour)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be sent, send nothing."
        )
        parser.add_argument(
            "--date",
            help="Act as if today were this date (YYYY-MM-DD). For checks and tests.",
        )

    def handle(self, *args, dry_run=False, date=None, **options):
        today = None
        if date:
            try:
                today = datetime.date.fromisoformat(date)
            except ValueError:
                raise CommandError("Date invalide : utilisez le format AAAA-MM-JJ.") from None

        report = send_reminders(today=today, dry_run=dry_run)

        prefix = "[simulation] " if dry_run else ""
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING(f"{prefix}{warning}"))
        for outcome in report.outcomes:
            line = f"{prefix}{outcome.subject} → {', '.join(outcome.recipients)}"
            if outcome.success:
                self.stdout.write(line)
            else:
                self.stdout.write(self.style.ERROR(f"{line} : ÉCHEC ({outcome.error})"))
        if not report.outcomes:
            self.stdout.write(f"{prefix}Aucun rappel à envoyer le {report.today:%d/%m/%Y}.")
        elif dry_run:
            self.stdout.write(f"[simulation] {len(report.outcomes)} email(s) seraient envoyés.")
        else:
            summary = f"{report.sent} email(s) envoyé(s), {report.failed} échec(s)."
            style = self.style.ERROR if report.failed else self.style.SUCCESS
            self.stdout.write(style(summary))
