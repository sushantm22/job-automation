"""One-command setup (bootstrap.py) and set-key's refusal to wait for keyboard input."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import bootstrap


def _fake_project(tmp_path: Path, monkeypatch) -> list[list[str]]:
    venv_dir = tmp_path / ".venv"
    req = tmp_path / "requirements.txt"
    req.write_text("typer\n")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "VENV", venv_dir)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS", req)
    monkeypatch.setattr(bootstrap, "STAMP", venv_dir / ".requirements.sha1")

    def fake_create(self, env_dir):
        py = bootstrap.venv_python(Path(env_dir))
        py.parent.mkdir(parents=True)
        py.write_text("")

    monkeypatch.setattr(bootstrap.venv.EnvBuilder, "create", fake_create)
    calls: list[list[str]] = []
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    return calls


def test_bootstrap_installs_once_then_skips_pip(tmp_path: Path, monkeypatch):
    calls = _fake_project(tmp_path, monkeypatch)
    assert bootstrap.main() == 0
    assert [c[1:3] for c in calls] == [["-m", "pip"], ["-m", "src.cli"], ["-m", "src.cli"]]
    assert calls[1][-1] == "prepare" and calls[2][-2:] == ["status", "--json"]

    calls.clear()
    assert bootstrap.main() == 0  # requirements unchanged: no pip
    assert all(c[2] != "pip" for c in calls)

    (tmp_path / "requirements.txt").write_text("typer\nrich\n")  # changed: install again
    calls.clear()
    bootstrap.main()
    assert calls[0][2] == "pip"


def test_bootstrap_stops_when_install_fails(tmp_path: Path, monkeypatch):
    _fake_project(tmp_path, monkeypatch)
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1))
    assert bootstrap.main() == 1
    assert not (tmp_path / ".venv" / ".requirements.sha1").exists()  # retried next time


def test_set_key_refuses_instead_of_waiting_for_keyboard(monkeypatch, capsys):
    import pytest
    import typer

    from src.cli import onboard_set_key

    class Terminal:  # stdin attached to a terminal, nothing piped in
        def isatty(self):
            return True

        def read(self):
            raise AssertionError("set-key waited for keyboard input")

    monkeypatch.setattr(sys, "stdin", Terminal())
    with pytest.raises(typer.Exit) as exc:
        onboard_set_key("NOTION_API_KEY", verify=False, as_json=False)
    assert exc.value.exit_code == 2
    assert "no value piped in" in capsys.readouterr().err


def test_discover_prints_progress_lines_while_tier1_runs(tmp_path):
    # Long runs must visibly keep moving: Copilot interrupted a silent run, thinking it had hung.
    import logging
    from unittest.mock import patch

    from src.config import Settings
    from src.db import init_db
    from src.discovery import engine as engine_mod

    db = tmp_path / "jobs.db"
    init_db(db)
    eng = engine_mod.JobDiscoveryEngine(settings=Settings(notion_enabled=False), db_path=db)
    lines: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: lines.append(record.getMessage())
    log = logging.getLogger("src.discovery.engine")
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.INFO)
    try:
        with patch.object(eng.registry, "ensure_seeded", return_value=0), \
             patch.object(eng.registry, "get_slugs_by_platform", return_value={"greenhouse": [f"c{i}" for i in range(30)]}), \
             patch.object(engine_mod, "fetch_greenhouse_jobs", return_value=[]):
            eng.run_tier1_direct_apis()
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
    assert "[Tier 1] Checking 30 company job boards..." in lines
    assert any(line.startswith("[Tier 1] 25/30 boards checked") for line in lines)


def test_show_progress_enables_only_project_logs_once():
    import logging

    from src.cli import _show_progress

    _show_progress()
    _show_progress()
    log = logging.getLogger("src")
    assert log.level == logging.INFO and not log.propagate
    assert sum(getattr(h, "_progress", False) for h in log.handlers) == 1
