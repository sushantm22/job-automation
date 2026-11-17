"""Regression tests for bugs found during the first real new-user onboarding test."""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch
import socket
from urllib.error import HTTPError, URLError

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

    # A missing key or other local problem isn't a sharing problem either.
    assert notion_client.explain_notion_error(ValueError("NOTION_API_KEY is not configured.")) == (
        "NOTION_API_KEY is not configured.", False
    )


# --- DNS failure showed the "share the page" tip and failed on a one-off hiccup ------

def _dns_failure() -> URLError:
    return URLError(socket.gaierror(8, "nodename nor servname provided, or not known"))


def test_explain_notion_error_reports_network_failure_without_sharing_tip():
    message, sharing_problem = notion_client.explain_notion_error(_dns_failure())
    assert sharing_problem is False
    assert "Couldn't reach Notion" in message and "network problem" in message


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_notion_request_retries_when_request_never_left_the_machine(monkeypatch):
    monkeypatch.setattr(notion_client.time, "sleep", lambda s: None)
    calls = []

    def flaky_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _dns_failure()
        return _FakeResponse(json.dumps({"id": "db-1", "url": "u"}).encode("utf-8"))

    with patch.object(notion_client.request, "urlopen", flaky_urlopen):
        res = notion_client.create_notion_job_database("a" * 32, api_token="ntn_fake_token")

    assert res["id"] == "db-1" and len(calls) == 2


def test_notion_request_does_not_retry_timeouts_or_notion_errors(monkeypatch):
    # A timeout may have reached Notion, so retrying a create could make a duplicate table.
    monkeypatch.setattr(notion_client.time, "sleep", lambda s: None)
    for failure in (URLError(TimeoutError("timed out")), _http_error(400, {"message": "bad"})):
        calls = []

        def failing_urlopen(req, timeout=None, failure=failure):
            calls.append(1)
            raise failure

        with patch.object(notion_client.request, "urlopen", failing_urlopen):
            try:
                notion_client.create_notion_job_database("a" * 32, api_token="ntn_fake_token")
            except URLError:
                pass
        assert len(calls) == 1, failure


def test_notion_request_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(notion_client.time, "sleep", lambda s: None)
    calls = []

    def down(req, timeout=None):
        calls.append(1)
        raise _dns_failure()

    with patch.object(notion_client.request, "urlopen", down):
        try:
            notion_client.create_notion_job_database("a" * 32, api_token="ntn_fake_token")
            raise AssertionError("expected failure")
        except URLError:
            pass
    assert len(calls) == len(notion_client.NETWORK_RETRY_DELAYS) + 1


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

    with patch.object(engine.registry, "ensure_seeded", return_value=0), \
         patch("src.discovery.engine.fetch_ashby_jobs", side_effect=fake_fetch):
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


# --- Antigravity run: sandbox without network, Notion table not visible, 50-job sync cap ---

def test_notion_table_is_created_inline_so_it_shows_on_the_page():
    sent: dict = {}

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data.decode("utf-8")))
        return _FakeResponse(json.dumps({"id": "db", "url": "u"}).encode("utf-8"))

    with patch.object(notion_client.request, "urlopen", fake_urlopen):
        notion_client.create_notion_job_database("a" * 32, api_token="ntn_fake_token")

    assert sent["is_inline"] is True


def test_key_check_offline_is_not_reported_as_failed(monkeypatch):
    from src import onboarding

    def offline(*a, **k):
        raise _dns_failure()

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", offline)
    assert onboarding.test_notion_key("ntn_real_looking_value") is None
    assert onboarding.test_apify_token("apify_api_value") is None

    def rejected(*a, **k):
        raise _http_error(401, {"message": "API token is invalid."})

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", rejected)
    assert onboarding.test_notion_key("ntn_wrong_value") is False


def test_check_keys_says_unreachable_not_failed_when_offline(tmp_path, monkeypatch):
    from src import onboard_steps, onboarding

    (tmp_path / ".env").write_text("NOTION_API_KEY=ntn_value\n", encoding="utf-8")
    monkeypatch.setattr(onboarding, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setitem(onboard_steps.SECRET_KEYS, "NOTION_API_KEY", lambda v: None)

    status = onboard_steps.check_keys()["NOTION_API_KEY"]
    assert status == onboard_steps.UNREACHABLE and "failed" not in status


def test_offline_tier1_run_is_flagged_and_does_not_stamp_boards(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    upsert_company("greenhouse", "a", db_path=db_file)
    upsert_company("greenhouse", "b", db_path=db_file)
    before = {r["slug"]: r["last_checked_at"] for r in list_companies(db_path=db_file)}
    engine = JobDiscoveryEngine(settings=Settings(), db_path=db_file)

    with patch.object(engine.registry, "ensure_seeded", return_value=0), \
         patch("src.discovery.engine.fetch_greenhouse_jobs", side_effect=_dns_failure()):
        engine.run_tier1_direct_apis(company_limit=10)

    assert engine.network_unavailable is True
    after = {r["slug"]: r["last_checked_at"] for r in list_companies(db_path=db_file)}
    assert after == before  # nothing was searched, so nothing is marked as checked

    # One reachable board means the network works: not flagged.
    with patch.object(engine.registry, "ensure_seeded", return_value=0), \
         patch("src.discovery.engine.fetch_greenhouse_jobs", side_effect=[_dns_failure(), []]):
        engine.run_tier1_direct_apis(company_limit=10)
    assert engine.network_unavailable is False


def test_discover_offline_exits_with_clear_message_and_keeps_step_open(tmp_path: Path, monkeypatch):
    from src import onboard_steps
    from src.cli import app

    monkeypatch.setattr(onboard_steps, "STATE_PATH", tmp_path / "state.json")
    offline_result = {
        "tier_counts": {}, "total_discovered": 0, "net_new_inserted": 0, "duplicates_prevented": 0,
        "network_unavailable": True,
    }
    with patch("src.cli.init_db"), patch("src.cli.JobDiscoveryEngine") as engine_cls:
        engine_cls.return_value.execute_all_tiers.return_value = offline_result
        result = CliRunner().invoke(app, ["discover", "--tiers", "1"])

    assert result.exit_code == 1
    assert "No internet access" in result.output
    assert onboard_steps.load_state().get("first_discovery") is None


def test_discover_notion_sync_is_capped_per_run_and_reports_what_is_waiting(tmp_path: Path):
    from src.db import upsert_jobs

    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    upsert_jobs([{"source": "t", "title": f"Job {i}", "url": f"https://x/{i}"} for i in range(5)], db_path=db_file)
    base = dict(notion_enabled=True, notion_auto_sync=True, notion_database_id="d" * 32, notion_api_token="ntn_x",
                jobhive_enabled=False)

    engine = JobDiscoveryEngine(settings=Settings(**base, notion_max_sync_per_run=200), db_path=db_file)
    with patch.object(engine, "run_tier1_direct_apis", return_value=[]), \
         patch("src.integrations.notion_client.sync_jobs_to_notion", return_value={"synced": 0}) as sync:
        result = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    assert sync.call_args.kwargs["limit"] == 200
    assert result["notion_pending"] == 5  # nothing was really pushed, so all 5 are still waiting

    # A cap of 0 means "sync everything in this run".
    engine = JobDiscoveryEngine(settings=Settings(**base, notion_max_sync_per_run=0), db_path=db_file)
    with patch.object(engine, "run_tier1_direct_apis", return_value=[]), \
         patch("src.integrations.notion_client.sync_jobs_to_notion", return_value={"synced": 0}) as sync:
        engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    assert sync.call_args.kwargs["limit"] is None


def test_sync_notion_command_pushes_all_pending_by_default():
    from src.cli import app

    with patch("src.integrations.notion_client.sync_jobs_to_notion", return_value={"synced": 3, "failed": 0}) as sync, \
         patch("src.integrations.notion_client.sync_closed_status", return_value={"closed": 0, "reopened": 0}):
        result = CliRunner().invoke(app, ["sync-notion"])
    assert result.exit_code == 0 and sync.call_args.kwargs["limit"] is None
