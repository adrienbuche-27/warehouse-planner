"""Start the application with waitress on http://localhost:8000 (Windows scheduled task).

Run by the task "Stockage - application" with pythonw.exe (no console window). Everything the
server prints goes to logs/app.log. Only this computer can reach the app (127.0.0.1).
The port is APP_PORT in .env (8000 by default).

Manual start, from the project folder:  .venv\\Scripts\\python.exe deploy\\windows\\run_server.py
"""

import datetime
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def redirect_output_to_log() -> None:
    """pythonw.exe has no console: everything Django and waitress print goes to logs/app.log
    (Django's console logging writes to sys.stderr, which now points to that file)."""
    logs = PROJECT / "logs"
    logs.mkdir(exist_ok=True)
    log_file = open(logs / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = log_file


def main() -> None:
    os.chdir(PROJECT)
    sys.path.insert(0, str(PROJECT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    redirect_output_to_log()

    from django.conf import settings
    from waitress import serve

    from config.wsgi import application

    port = settings.APP_PORT  # APP_PORT in .env, 8000 by default
    print(f"=== {datetime.datetime.now():%d/%m/%Y %H:%M:%S} démarrage sur http://localhost:{port}")
    # 127.0.0.1: only this computer can open the application.
    serve(application, listen=f"127.0.0.1:{port}", threads=4)


if __name__ == "__main__":
    main()
