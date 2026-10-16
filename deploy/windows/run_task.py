"""Run a management command and append its output to logs/<command>.log (Windows tasks).

Used by the scheduled tasks with pythonw.exe (no console window), for example:
    .venv\\Scripts\\pythonw.exe deploy\\windows\\run_task.py send_reminders
    .venv\\Scripts\\pythonw.exe deploy\\windows\\run_task.py backup_data
"""

import os
import sys
import traceback
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ALLOWED_COMMANDS = {"send_reminders", "backup_data"}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ALLOWED_COMMANDS:
        print(f"usage: run_task.py {{{'|'.join(sorted(ALLOWED_COMMANDS))}}} [options]")
        return 2
    command, options = argv[1], argv[2:]

    os.chdir(PROJECT)
    sys.path.insert(0, str(PROJECT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    logs = PROJECT / "logs"
    logs.mkdir(exist_ok=True)

    with open(logs / f"{command}.log", "a", encoding="utf-8") as log:
        log.write(f"\n=== {command} {' '.join(options)}\n")
        try:
            import django

            django.setup()
            from django.core.management import call_command
            from django.utils import timezone

            log.write(f"{timezone.localtime():%d/%m/%Y %H:%M:%S} (heure de Bruxelles)\n")
            call_command(command, *options, stdout=log, stderr=log)
        except Exception:  # noqa: BLE001 - any failure must end up in the log file
            traceback.print_exc(file=log)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
