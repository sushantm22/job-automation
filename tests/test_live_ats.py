"""Live Keka + SuccessFactors via the ats-scrapers package (core install only)."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from src.config import Settings
from src.db import init_db, upsert_company
from src.discovery import ats_scrapers_adapter as adapter
from src.discovery.engine import JobDiscoveryEngine


def _job(**kw):
    base = dict(title="Senior Sales Manager", company="Wipro Limited", location="Pune", country_iso="IN",
                is_remote=False, url="https://careers.wipro.com/job/1", description="Lead sales.",
                posted_at=datetime(2026, 11, 15, tzinfo=timezone.utc))
    return SimpleNamespace(**(base | kw))


def test_evasion_extras_are_not_installed():
    # The project only uses ats-scrapers' core install; its impersonation extras must stay out.
    for module in ("httpcloak", "cloakbrowser"):
        assert importlib.util.find_spec(module) is None, f"{module} must not be installed"


def test_only_plain_http_scrapers_are_allowed():
    assert adapter._scraper_class("keka").__name__ == "KekaScraper"
    assert adapter._scraper_class("successfactors").__name__ == "SuccessFactorsScraper"

    class Impersonating:
        fetch_engine = "cloak"

    class Escalating:
        fetch_engine, fetch_escalate = "httpx", True

    for cls in (Impersonating, Escalating):
        with patch("ats_scrapers.scrapers.ScraperRegistry.get", return_value=cls):
            with pytest.raises(ValueError, match="impersonation"):
                adapter._scraper_class("keka")


def test_job_conversion_and_india_country_code():
    rec = adapter.job_to_record(_job(), "successfactors")
    assert (rec.source, rec.company, rec.location) == ("successfactors", "Wipro Limited", "Pune, India")
    assert rec.posted_at.startswith("2026-11-15") and rec.url == "https://careers.wipro.com/job/1"

    assert adapter.job_to_record(_job(location="IN"), "successfactors").location == "India"
    assert adapter.job_to_record(_job(location="Bengaluru, India"), "keka").location == "Bengaluru, India"
    assert adapter.job_to_record(_job(is_remote=True, location="India"), "keka").location == "Remote, India"
    assert adapter.job_to_record(_job(posted_at=None), "successfactors").posted_at is None


def test_fetch_uses_fast_mode_without_descriptions():
    created = {}

    class FakeScraper:
        fetch_engine, fetch_escalate = "httpx", False

        def __init__(self, slug, **kw):
            created.update(slug=slug, **kw)

        def fetch(self):
            return [_job()]

    with patch("ats_scrapers.scrapers.ScraperRegistry.get", return_value=FakeScraper):
        jobs = adapter.fetch_live_ats_jobs("keka", "https://kpgroup.keka.com/careers")

    assert created["slug"] == "https://kpgroup.keka.com/careers" and created["include_descriptions"] is False
    assert len(jobs) == 1 and jobs[0].source == "keka"


def test_tier1_dispatches_keka_and_successfactors(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    upsert_company("keka", "https://kpgroup.keka.com/careers", db_path=db)
    upsert_company("successfactors", "careers.wipro.com", db_path=db)
    engine = JobDiscoveryEngine(settings=Settings(), db_path=db)

    calls = []
    with patch.object(engine.registry, "ensure_seeded", return_value=0), \
         patch("src.discovery.engine.fetch_live_ats_jobs",
               side_effect=lambda p, s: calls.append((p, s)) or [adapter.job_to_record(_job(), p)]):
        jobs = engine.run_tier1_direct_apis(company_limit=10)

    assert sorted(calls) == [("keka", "https://kpgroup.keka.com/careers"), ("successfactors", "careers.wipro.com")]
    assert len(jobs) == 2


def test_companies_yaml_ships_verified_live_companies():
    from src.discovery.registry import DEFAULT_YAML_PATH

    data = yaml.safe_load(DEFAULT_YAML_PATH.read_text(encoding="utf-8"))
    assert "careers.wipro.com" in data["successfactors"]
    assert all(u.startswith("https://") and ".keka.com/careers" in u for u in data["keka"])
