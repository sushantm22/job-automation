"""Roles are per user: nothing ships by default, and every tier follows the user's roles."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import yaml
from typer.testing import CliRunner

from src.config import Settings
from src.db import init_db
from src.discovery import firecrawl_adapter
from src.discovery.apify_adapter import fetch_apify_naukri_jobs
from src.discovery.engine import JobDiscoveryEngine
from src.discovery.firecrawl_adapter import (
    COMPANIES_YAML_PATH,
    build_portal_url,
    fetch_firecrawl_portal_jobs,
    parse_firecrawl_extracted_jobs,
)
from src.discovery.jobspy_adapter import fetch_jobspy_jobs


def test_project_ships_no_default_roles():
    from src.config import CONFIG_PATH

    assert yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["search"]["keywords"] == []
    assert Settings().search_keywords == []


def test_engine_refuses_to_run_without_roles_instead_of_flooding_the_database(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    engine = JobDiscoveryEngine(settings=Settings(notion_enabled=False, jobhive_enabled=False), db_path=db)
    with patch.object(engine, "run_tier1_direct_apis") as tier1:
        try:
            engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
        except ValueError as err:
            assert "set-search" in str(err)
        else:
            raise AssertionError("expected ValueError")
    tier1.assert_not_called()


def test_discover_command_explains_how_to_set_roles_and_exits_1():
    from src.cli import app

    with patch("src.cli.load_settings", return_value=Settings()), patch("src.cli.JobDiscoveryEngine") as engine_cls:
        result = CliRunner().invoke(app, ["discover", "--tiers", "1"])
    assert result.exit_code == 1
    assert "onboard set-search --roles" in result.output
    engine_cls.assert_not_called()


def test_apify_and_jobspy_do_nothing_without_roles():
    assert fetch_apify_naukri_jobs([], ["India"], api_token="tok") == []
    with patch.dict("sys.modules", {"jobspy": type("J", (), {"scrape_jobs": staticmethod(lambda **kw: 1 / 0)})}):
        assert fetch_jobspy_jobs([], ["India"]) == []  # never calls scrape_jobs (it would raise)


# ---- Firecrawl (tier 4) follows the roles --------------------------------------------------

def test_portal_url_query_placeholder_uses_the_first_role_url_encoded():
    url = "https://example.com/jobs?q={query}&location=India"
    assert build_portal_url(url, ["Key Account Manager", "Sales Manager"]) == (
        "https://example.com/jobs?q=" + quote("Key Account Manager", safe="") + "&location=India"
    )
    assert build_portal_url(url, []) == "https://example.com/jobs?q=&location=India"
    assert build_portal_url("https://example.com/careers", ["Sales Manager"]) == "https://example.com/careers"


def test_shipped_portals_have_no_hardcoded_software_searches():
    portals = yaml.safe_load(COMPANIES_YAML_PATH.read_text(encoding="utf-8"))["enterprise_portals"]
    with_query = [p for p in portals if "{query}" in p["url"]]
    assert len(with_query) == 13
    assert not any("software" in p["url"].lower() for p in portals)


def test_fetch_firecrawl_scrapes_the_portal_url_filled_with_the_role():
    portals = [{"name": "Acme", "url": "https://acme.test/jobs?q={query}"}]
    with patch.object(firecrawl_adapter, "scrape_portal_with_firecrawl", return_value=[]) as scrape:
        fetch_firecrawl_portal_jobs(portals=portals, api_key="k", roles=["Brand Manager", "Sales Manager"])
    assert scrape.call_args.kwargs["portal_url"] == "https://acme.test/jobs?q=Brand%20Manager"
    assert scrape.call_args.kwargs["roles"] == ["Brand Manager", "Sales Manager"]


def test_extraction_prompt_asks_for_the_users_roles_not_technology_jobs():
    sent = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"success": true, "data": {"extract": {"jobs": []}}}'

    def fake_urlopen(req, timeout=None):
        import json
        sent.update(json.loads(req.data.decode("utf-8")))
        return Resp()

    with patch.object(firecrawl_adapter.request, "urlopen", fake_urlopen):
        firecrawl_adapter.scrape_portal_with_firecrawl("https://x.test", "Acme", "k", roles=["Brand Manager", "Sales Manager"])
    prompt = sent["extract"]["prompt"]
    assert "Brand Manager, Sales Manager" in prompt
    assert "technology" not in prompt and "engineering" not in prompt


def test_markdown_fallback_keeps_only_links_matching_the_roles():
    data = {"markdown": """
        - [Senior Sales Manager - West](https://x.test/jobs/1)
        - [Salesforce Developer](https://x.test/jobs/2)
        - [Privacy Policy](https://x.test/privacy)
    """}
    with_roles = parse_firecrawl_extracted_jobs(data, default_company="Acme", roles=["Sales Manager"])
    assert [r.title for r in with_roles] == ["Senior Sales Manager - West"]

    generic = parse_firecrawl_extracted_jobs(data, default_company="Acme")  # no roles: generic job words
    assert [r.title for r in generic] == ["Senior Sales Manager - West", "Salesforce Developer"]


def test_untitled_items_are_skipped_instead_of_labelled_engineering_role():
    data = {"extract": {"jobs": [{"url": "https://x.test/1"}, {"title": "Brand Manager", "url": "https://x.test/2"}]}}
    records = parse_firecrawl_extracted_jobs(data, default_company="Acme")
    assert [r.title for r in records] == ["Brand Manager"]
