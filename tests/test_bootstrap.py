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
