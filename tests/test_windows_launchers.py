"""M8: the Python launchers used by the Windows scheduled tasks (deploy/windows/)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / "windows" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_task_refuses_unknown_commands(capsys):
    run_task = load("run_task")
    assert run_task.main(["run_task.py", "flush"]) == 2
    assert run_task.main(["run_task.py"]) == 2
    assert "usage" in capsys.readouterr().out


@pytest.mark.django_db
def test_run_task_writes_the_command_output_to_its_log(tmp_path, monkeypatch):
    run_task = load("run_task")
    monkeypatch.setattr(run_task, "PROJECT", tmp_path)
    monkeypatch.chdir(tmp_path)
    assert run_task.main(["run_task.py", "send_reminders", "--dry-run"]) == 0
    log = (tmp_path / "logs" / "send_reminders.log").read_text(encoding="utf-8")
    assert "=== send_reminders --dry-run" in log
    assert "(heure de Bruxelles)" in log
    assert "[simulation]" in log


@pytest.mark.django_db
def test_run_task_logs_failures(tmp_path, monkeypatch):
    run_task = load("run_task")
    monkeypatch.setattr(run_task, "PROJECT", tmp_path)
    monkeypatch.chdir(tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("disque plein")

    monkeypatch.setattr("django.core.management.call_command", broken)
    assert run_task.main(["run_task.py", "backup_data"]) == 1
    log = (tmp_path / "logs" / "backup_data.log").read_text(encoding="utf-8")
    assert "RuntimeError: disque plein" in log


def test_server_listens_on_localhost_only():
    source = (ROOT / "deploy" / "windows" / "run_server.py").read_text(encoding="utf-8")
    assert 'listen=f"127.0.0.1:{port}"' in source
