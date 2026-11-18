"""
One-command setup: python3 bootstrap.py   (Windows: py -3 bootstrap.py)

Creates the virtualenv, installs requirements (skipped when requirements.txt is unchanged), runs
`onboard prepare` (creates .env, the database and the company list) and prints `onboard status --json`.
Standard library only, so it runs before anything is installed. Safe to re-run.

AI assistants: run this as ONE command instead of the separate steps, so the user approves once.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha1"
MIN_PYTHON = (3, 10)


def venv_python(venv_dir: Path | None = None) -> Path:
    return (venv_dir or VENV) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash() -> str:
    return hashlib.sha1(REQUIREMENTS.read_bytes()).hexdigest()


def needs_install() -> bool:
    return not STAMP.exists() or STAMP.read_text().strip() != requirements_hash()


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


def main() -> int:
    os.chdir(ROOT)
    if sys.version_info < MIN_PYTHON:
        print(f"Python {'.'.join(map(str, MIN_PYTHON))}+ is required; this is {sys.version.split()[0]}. "
              "Install it from https://www.python.org/downloads/ (macOS: brew install python).")
        return 1
    step(f"Python {sys.version.split()[0]}")

    py = venv_python()
    if not py.exists():
        step("Creating virtual environment in .venv")
        venv.EnvBuilder(with_pip=True).create(VENV)

    if needs_install():
        step("Installing dependencies (1-3 minutes, needs internet)")
        result = subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                                 "-r", str(REQUIREMENTS)])
        if result.returncode != 0:
            print("Dependency install failed (see above). If it mentions network or DNS errors, "
                  "run this again with internet access.")
            return result.returncode
        STAMP.write_text(requirements_hash())
    else:
        step("Dependencies already installed")

    step("Preparing .env, database and company list")
    result = subprocess.run([str(py), "-m", "src.cli", "onboard", "prepare"])
    if result.returncode != 0:
        return result.returncode

    step(f"Done. Use this Python for every other command: {py.relative_to(ROOT)}")
    step("Onboarding status:")
    return subprocess.run([str(py), "-m", "src.cli", "onboard", "status", "--json"]).returncode


if __name__ == "__main__":
    sys.exit(main())
