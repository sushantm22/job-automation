from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import src.db
from src import onboard_steps as steps
from src import onboarding
from src.config import ROOT, load_settings
from src.db import init_db, upsert_jobs


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    """A fake project root: every path onboarding touches points into tmp_path."""
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    shutil.copy(ROOT / "data" / "profile.example.json", tmp_path / "data" / "profile.example.json")
    shutil.copy(ROOT / "data" / "candidate_answers.example.json", tmp_path / "data" / "candidate_answers.example.json")

    monkeypatch.setattr(steps, "ROOT", tmp_path)
    monkeypatch.setattr(steps, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(steps, "STATE_PATH", tmp_path / "data" / "onboarding_state.json")
    monkeypatch.setattr(steps, "PROFILE_PATH", tmp_path / "data" / "profile.json")
    monkeypatch.setattr(steps, "PROFILE_EXAMPLE_PATH", tmp_path / "data" / "profile.example.json")
    monkeypatch.setattr(steps, "ANSWERS_PATH", tmp_path / "data" / "candidate_answers_reference.json")
    monkeypatch.setattr(steps, "ANSWERS_EXAMPLE_PATH", tmp_path / "data" / "candidate_answers.example.json")
    monkeypatch.setattr(onboarding, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(src.db, "DB_PATH", tmp_path / "data" / "jobs.db")
    for name in ("NOTION_API_KEY", "NOTION_DATABASE_ID", "APIFY_API_TOKEN", "FIRECRAWL_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # Online key checks must never hit the network in tests.
    monkeypatch.setitem(steps.SECRET_KEYS, "NOTION_API_KEY", lambda v: v == "ntn_good_value")
    monkeypatch.setitem(steps.SECRET_KEYS, "GEMINI_API_KEY", lambda v: False)
    return tmp_path


def test_fresh_user_starts_at_search_step(sandbox: Path):
    status = steps.get_status()
    assert status["next_step"] == "search"
    assert status["complete"] is False
    assert status["steps"]["profile"]["missing"] == ["profile.json not created"]


def test_set_search_writes_local_override_not_shared_config(sandbox: Path):
    shared_before = (sandbox / "config.yaml").read_text(encoding="utf-8")

    res = steps.set_search(roles="Backend Engineer, Python Developer", locations="Pune, Remote")

    assert res["roles"] == ["Backend Engineer", "Python Developer"]
    assert (sandbox / "config.yaml").read_text(encoding="utf-8") == shared_before
    local = yaml.safe_load((sandbox / "config.local.yaml").read_text(encoding="utf-8"))
    assert local == {"search": {"keywords": ["Backend Engineer", "Python Developer"], "locations": ["Pune", "Remote"]}}
    # Untouched settings still come from config.yaml.
    assert load_settings(sandbox / "config.yaml").exclude_keywords == ["intern", "unpaid"]
    assert steps.get_status()["next_step"] == "api_keys"


def test_set_search_without_options_keeps_defaults_and_completes_step(sandbox: Path):
    res = steps.set_search()
    assert not (sandbox / "config.local.yaml").exists()
    assert "SDET" in res["roles"]
    assert steps.get_status()["steps"]["search"]["done"] is True


def test_set_search_rejects_empty_list(sandbox: Path):
    with pytest.raises(ValueError):
        steps.set_search(roles=" , ")


def test_read_env_file_ignores_inline_comments(sandbox: Path):
    (sandbox / ".env").write_text("GEMINI_API_KEY=      # free key from AI Studio\nDATABASE_PATH=data/jobs.db\n", encoding="utf-8")
    env = onboarding.read_env_file()
    assert env["GEMINI_API_KEY"] == ""
    assert env["DATABASE_PATH"] == "data/jobs.db"


def test_set_key_saves_and_reports_verification(sandbox: Path):
    assert steps.set_key("NOTION_API_KEY", " ntn_good_value \n") == {"saved": "NOTION_API_KEY", "verified": True}
    assert steps.set_key("GEMINI_API_KEY", "AIza-bad")["verified"] is False
    assert steps.set_key("FIRECRAWL_API_KEY", "fc-x")["verified"] is None

    env = onboarding.read_env_file()
    assert env["NOTION_API_KEY"] == "ntn_good_value"
    assert steps.get_status()["steps"]["api_keys"]["keys_set"]["FIRECRAWL_API_KEY"] is True

    with pytest.raises(ValueError):
        steps.set_key("SOME_OTHER_VAR", "x")
    with pytest.raises(ValueError):
        steps.set_key("APIFY_API_TOKEN", "   ")


def test_set_profile_fills_fields_and_copies_external_resume(sandbox: Path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("downloads") / "My CV.PDF"
    outside.write_bytes(b"%PDF-1.4")

    res = steps.set_profile({
        "first_name": "Asha", "last_name": "Rao", "email": "asha@example.com", "phone": "+91 90000 00000",
        "city": "Pune", "country": "India", "linkedin": "https://linkedin.com/in/asha",
        "notice_period_days": "30", "resume": str(outside),
    })

    assert res["missing"] == []
    assert res["resume"] == "data/resume.pdf"
    assert (sandbox / "data" / "resume.pdf").read_bytes() == b"%PDF-1.4"
    profile = json.loads((sandbox / "data" / "profile.json").read_text(encoding="utf-8"))
    assert profile["personal"]["location"]["city"] == "Pune"
    assert profile["preferences"]["notice_period_days"] == 30
    assert (sandbox / "data" / "candidate_answers_reference.json").exists()

    with pytest.raises(ValueError):
        steps.set_profile({"salary": "lots"})


def test_walkthrough_reaches_complete(sandbox: Path):
    steps.set_search()
    steps.skip_step("api_keys")
    assert steps.get_status()["next_step"] == "notion"
    steps.skip_step("notion")
    assert steps.get_status()["next_step"] == "first_discovery"

    init_db(sandbox / "data" / "jobs.db")
    upsert_jobs([{"source": "t", "company": "C", "title": "SDET", "location": "Remote", "url": "https://x/1"}],
                db_path=sandbox / "data" / "jobs.db")
    assert steps.get_status()["next_step"] == "profile"

    steps.skip_step("profile")
    status = steps.get_status()
    assert status["complete"] is True and status["steps"]["profile"]["skipped"] is True

    with pytest.raises(ValueError):
        steps.skip_step("search")


def test_cli_set_key_reads_stdin_and_never_echoes_value(sandbox: Path):
    from src.cli import app

    result = CliRunner().invoke(app, ["onboard", "set-key", "NOTION_API_KEY"], input="ntn_good_value\n")
    assert result.exit_code == 0, result.output
    assert "verified online" in result.output
    assert "ntn_good_value" not in result.output


def test_cli_status_json_is_machine_readable(sandbox: Path):
    from src.cli import app

    result = CliRunner().invoke(app, ["onboard", "status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["next_step"] == "search"


# --- prepare / check-keys (bug: .env did not exist when the user was asked to add keys) ---

def test_prepare_creates_env_db_and_registry_before_any_question(sandbox: Path, monkeypatch):
    shutil.copy(ROOT / ".env.example", sandbox / ".env.example")
    monkeypatch.setattr(onboarding, "ENV_EXAMPLE_PATH", sandbox / ".env.example")
    assert steps.get_status()["env_file_exists"] is False

    res = steps.prepare()

    assert res["env_created"] is True
    assert (sandbox / ".env").read_text(encoding="utf-8") == (sandbox / ".env.example").read_text(encoding="utf-8")
    assert res["registry_boards"] > 0 and (sandbox / "data" / "jobs.db").exists()
    assert steps.get_status()["env_file_exists"] is True
    # The template's blank placeholders must not count as keys.
    assert not any(steps.get_status()["steps"]["api_keys"]["keys_set"].values())

    # Re-running never overwrites keys the user already added.
    (sandbox / ".env").write_text("NOTION_API_KEY=ntn_good_value\n", encoding="utf-8")
    again = steps.prepare()
    assert again["env_created"] is False and again["registry_seeded"] == 0
    assert onboarding.read_env_file()["NOTION_API_KEY"] == "ntn_good_value"


def test_prepare_creates_env_even_without_template(sandbox: Path, monkeypatch):
    monkeypatch.setattr(onboarding, "ENV_EXAMPLE_PATH", sandbox / "missing.env.example")
    assert steps.prepare()["env_created"] is True
    assert (sandbox / ".env").exists()


def test_check_keys_reports_status_without_values(sandbox: Path):
    (sandbox / ".env").write_text(
        "NOTION_API_KEY=ntn_good_value\nGEMINI_API_KEY=AIza-bad\nFIRECRAWL_API_KEY=fc-x\n", encoding="utf-8"
    )
    assert steps.check_keys() == {
        "NOTION_API_KEY": "verified",
        "APIFY_API_TOKEN": "missing",
        "FIRECRAWL_API_KEY": "set (no online check)",
        "GEMINI_API_KEY": "failed",
    }
