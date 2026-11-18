from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from src import onboarding
from src.config import DEFAULT_DATABASE_PATH, ROOT, Settings, resolve_database_path
from src.db import init_db, upsert_company
from src.discovery.engine import JobDiscoveryEngine
from src.discovery.registry import CompanyRegistry


# --- DATABASE_PATH -----------------------------------------------------------------

def test_resolve_database_path_relative_absolute_and_empty(tmp_path: Path):
    assert resolve_database_path(None) == DEFAULT_DATABASE_PATH
    assert resolve_database_path("  ") == DEFAULT_DATABASE_PATH
    assert resolve_database_path("data/alice.db") == ROOT / "data" / "alice.db"
    assert resolve_database_path(str(tmp_path / "x.db")) == tmp_path / "x.db"


def test_database_path_env_is_used_by_db_module(tmp_path: Path):
    # DB_PATH is resolved at import, so check it in a fresh interpreter, run from another cwd.
    custom = tmp_path / "isolated.db"
    env = {**os.environ, "DATABASE_PATH": str(custom), "PYTHONPATH": str(ROOT)}
    out = subprocess.run(
        [sys.executable, "-c", "from src.db import DB_PATH; print(DB_PATH)"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == str(custom)


# --- First-run company registry ----------------------------------------------------

def _write_yaml(path: Path) -> Path:
    path.write_text(yaml.safe_dump({
        "greenhouse": ["stripe"],
        "lever": ["plivo"],
        "enterprise_portals": [{"name": "Google", "url": "https://careers.google.com"}],
    }), encoding="utf-8")
    return path


def test_ensure_seeded_loads_yaml_into_empty_registry(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    registry = CompanyRegistry(db_path=db_file)

    assert registry.ensure_seeded(_write_yaml(tmp_path / "companies.yaml")) == 2
    assert registry.get_slugs_by_platform() == {"greenhouse": ["stripe"], "lever": ["plivo"]}
    # Second call is a no-op.
    assert registry.ensure_seeded(tmp_path / "companies.yaml") == 0


def test_ensure_seeded_never_resurrects_pruned_boards_but_adds_new_ones(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    upsert_company("greenhouse", "stripe", status="inactive", db_path=db_file)  # pruned earlier

    registry = CompanyRegistry(db_path=db_file)
    # companies.yaml lists stripe (pruned) and plivo (new to this user).
    assert registry.ensure_seeded(_write_yaml(tmp_path / "companies.yaml")) == 1
    assert registry.get_slugs_by_platform() == {"lever": ["plivo"]}


def test_fresh_database_tier1_polls_boards_from_companies_yaml(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    engine = JobDiscoveryEngine(settings=Settings(), db_path=db_file)

    with patch("src.discovery.engine.fetch_greenhouse_jobs", return_value=[]) as gh, \
         patch("src.discovery.engine.fetch_lever_jobs", return_value=[]) as lv, \
         patch("src.discovery.engine.fetch_ashby_jobs", return_value=[]) as ab, \
         patch("src.discovery.engine.fetch_smartrecruiters_jobs", return_value=[]) as sr:
        engine.run_tier1_direct_apis(company_limit=5)

    assert engine.registry_seeded > 0
    assert gh.call_count + lv.call_count + ab.call_count + sr.call_count == 5


# --- Profile ------------------------------------------------------------------------

def test_ensure_file_from_example_creates_only_when_missing(tmp_path: Path):
    example = tmp_path / "profile.example.json"
    example.write_text('{"personal": {}}', encoding="utf-8")
    target = tmp_path / "profile.json"

    assert onboarding.ensure_file_from_example(target, example) is True
    target.write_text('{"edited": true}', encoding="utf-8")
    assert onboarding.ensure_file_from_example(target, example) is False
    assert target.read_text(encoding="utf-8") == '{"edited": true}'


def test_missing_profile_fields_flags_blanks_and_missing_resume(tmp_path: Path):
    profile = onboarding.load_profile(ROOT / "data" / "profile.example.json")
    missing = onboarding.missing_profile_fields(profile, root=tmp_path)
    assert "First name" in missing and "Email" in missing
    assert any(m.startswith("Resume file path") for m in missing)
    assert "GitHub URL (optional)" not in missing

    for keys, _label, _kind, _req in onboarding.PROFILE_PROMPTS:
        onboarding._set_nested(profile, keys, "x")
    onboarding._set_nested(profile, ("files", "resume"), "resume.pdf")
    (tmp_path / "resume.pdf").write_bytes(b"%PDF")
    assert onboarding.missing_profile_fields(profile, root=tmp_path) == []


# --- Notion table provisioning ------------------------------------------------------

DB_UUID = "11111111-2222-3333-4444-555555555555"
PARENT_URL = "https://www.notion.so/me/Job-Hunt-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_provision_notion_table_returns_env_values():
    with patch(
        "src.integrations.notion_client.create_notion_job_database",
        return_value={"id": DB_UUID, "url": "https://notion.so/table"},
    ) as create:
        env, url = onboarding.provision_notion_table("ntn_fake_token", PARENT_URL)

    assert create.call_args.kwargs["api_token"] == "ntn_fake_token"
    assert env == {
        "NOTION_DATABASE_ID": DB_UUID.replace("-", ""),
        "NOTION_PARENT_PAGE_ID": "a" * 32,
    }
    assert url == "https://notion.so/table"


def test_init_notion_db_saves_ids_to_env(tmp_path: Path, monkeypatch):
    from src.cli import app

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_API_KEY=ntn_fake_token\n", encoding="utf-8")
    monkeypatch.setattr(onboarding, "ENV_PATH", env_file)

    with patch(
        "src.integrations.notion_client.create_notion_job_database",
        return_value={"id": DB_UUID, "url": "https://notion.so/table"},
    ):
        result = CliRunner().invoke(app, ["init-notion-db", "--parent-page-id", PARENT_URL])

    assert result.exit_code == 0, result.output
    saved = onboarding.read_env_file()
    assert saved["NOTION_DATABASE_ID"] == DB_UUID.replace("-", "")
    assert saved["NOTION_PARENT_PAGE_ID"] == "a" * 32
    assert saved["NOTION_API_KEY"] == "ntn_fake_token"  # existing keys preserved
