"""Regression tests for bugs found during the first real new-user onboarding test."""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from typer.testing import CliRunner

import src.config
from src.config import Settings
from src.db import init_db, list_companies, upsert_company
from src.discovery.engine import JobDiscoveryEngine
from src.integrations import notion_client


def _http_error(code: int, body: dict | None = None) -> HTTPError:
    payload = io.BytesIO(json.dumps(body or {}).encode("utf-8"))
    return HTTPError("https://api.notion.com/v1/databases", code, "err", {}, payload)


# --- Notion table creation failed with 400 (unsupported "black" color) -------------

def test_notion_table_schema_uses_only_colors_notion_accepts():
    sent: dict = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data.decode("utf-8")))
        return FakeResponse(json.dumps({"id": "db", "url": "u"}).encode("utf-8"))

    with patch.object(notion_client.request, "urlopen", fake_urlopen):
        notion_client.create_notion_job_database("a" * 32, api_token="ntn_fake_token")

    colors = {
        option["color"]
        for prop in sent["properties"].values()
        for option in prop.get("select", {}).get("options", [])
    }
    assert colors and colors <= notion_client.NOTION_SELECT_COLORS


def test_explain_notion_error_shows_notion_message_and_tip_only_for_access_errors():
    bad_request = _http_error(400, {"message": "body failed validation: color should be ..."})
    assert notion_client.explain_notion_error(bad_request) == ("body failed validation: color should be ...", False)

    not_shared = _http_error(404, {"message": "Could not find page with ID: abc"})
    assert notion_client.explain_notion_error(not_shared) == ("Could not find page with ID: abc", True)

    assert notion_client.explain_notion_error(ValueError("boom")) == ("boom", True)


def test_init_notion_db_400_prints_real_reason_without_sharing_tip():
    from src.cli import app

    err = _http_error(400, {"message": "body failed validation"})
    with patch("src.integrations.notion_client.create_notion_job_database", side_effect=err):
        result = CliRunner().invoke(app, ["init-notion-db", "--parent-page-id", "a" * 32])

    assert result.exit_code == 1
    assert "body failed validation" in result.output
    assert "Connections" not in result.output


# --- Dead company boards printed a 404 on every run ----------------------------------

def test_tier1_deactivates_board_on_404_but_not_on_other_errors(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    upsert_company("ashby", "gone", name="Gone Inc", db_path=db_file)
    upsert_company("ashby", "flaky", name="Flaky Inc", db_path=db_file)
    engine = JobDiscoveryEngine(settings=Settings(), db_path=db_file)

    def fake_fetch(slug):
        raise _http_error(404) if slug == "gone" else _http_error(503)

    with patch("src.discovery.engine.fetch_ashby_jobs", side_effect=fake_fetch):
        engine.run_tier1_direct_apis(company_limit=10)

    rows = {r["slug"]: r for r in list_companies(status=None, db_path=db_file)}
    assert rows["gone"]["status"] == "inactive"
    assert rows["gone"]["name"] == "Gone Inc"  # name preserved
    assert rows["flaky"]["status"] == "active"
    assert engine.registry.get_slugs_by_platform() == {"ashby": ["flaky"]}


# --- Tests depended on the developer's own config.local.yaml ------------------------

def test_tests_never_see_the_developers_local_config():
    real_local = src.config.CONFIG_PATH.with_name("config.local.yaml")
    assert src.config.local_config_path() != real_local
    # Shared defaults are what tests see, whatever roles the developer saved locally.
    assert "SDET" in src.config.load_settings().search_keywords
