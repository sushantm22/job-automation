from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from src.config import Settings
from src.db import init_db, list_companies, upsert_company
from src.discovery import harvester, smartrecruiters
from src.discovery.engine import JobDiscoveryEngine
from src.discovery.harvester import extract_ats_slugs, probe_company_board
from src.discovery.registry import CompanyRegistry

# Shape copied from a live api.smartrecruiters.com response (trimmed).
PAGE = {
    "totalFound": 2,
    "content": [
        {
            "id": "744000098",
            "name": "Senior Sales Manager",
            "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
            "location": {"city": "hosur road bangalore", "country": "in", "remote": False,
                         "fullLocation": "hosur road bangalore, , India"},
            "releasedDate": "2026-11-16T17:23:48.976Z",
        },
        {
            "id": "744000099",
            "name": "Area Sales Manager",
            "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
            "location": {"city": "pune", "country": "in", "remote": True, "fullLocation": "pune, , India"},
            "releasedDate": "2026-11-15T10:00:00.000Z",
        },
    ],
}


def test_parse_postings_builds_clean_records():
    jobs = smartrecruiters.parse_smartrecruiters_postings(PAGE, "BoschGroup")

    assert [j.title for j in jobs] == ["Senior Sales Manager", "Area Sales Manager"]
    assert jobs[0].company == "Bosch Group"
    assert jobs[0].location == "hosur road bangalore, India"
    assert jobs[1].location == "Remote, pune, India"
    assert jobs[0].url == "https://jobs.smartrecruiters.com/BoschGroup/744000098"
    assert jobs[0].source == "smartrecruiters" and jobs[0].posted_at.startswith("2026-11-16")


def test_fetch_pages_until_total_found():
    pages = [
        {"totalFound": 3, "content": [dict(PAGE["content"][0], id=str(i)) for i in range(2)]},
        {"totalFound": 3, "content": [dict(PAGE["content"][0], id="2")]},
    ]
    with patch.object(smartrecruiters, "fetch_smartrecruiters_page", side_effect=pages) as page:
        jobs = smartrecruiters.fetch_smartrecruiters_jobs("BoschGroup", page_size=2)

    assert len(jobs) == 3 and page.call_count == 2
    assert page.call_args_list[1].kwargs["offset"] == 2
    assert page.call_args_list[0].kwargs["country"] == "in"  # India filter applied server-side


def test_probe_counts_only_companies_with_postings():
    with patch.object(smartrecruiters, "fetch_smartrecruiters_page", return_value=PAGE):
        ok = probe_company_board("smartrecruiters", "BoschGroup")
    assert ok["valid"] is True and ok["job_count"] == 2 and ok["name"] == "Bosch Group"

    # Unknown identifiers come back as HTTP 200 with zero postings.
    with patch.object(smartrecruiters, "fetch_smartrecruiters_page", return_value={"totalFound": 0, "content": []}):
        empty = probe_company_board("smartrecruiters", "NoSuchCompany")
    assert empty["valid"] is False and empty["status"] == "empty"  # not "not_found": never auto-pruned


def test_harvester_recognises_smartrecruiters_links_case_sensitively():
    found = extract_ats_slugs("Apply: https://jobs.smartrecruiters.com/BoschGroup/744000098-senior-sales-manager")
    assert {"platform": "smartrecruiters", "slug": "BoschGroup"} in found


def test_tier1_polls_smartrecruiters_boards(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    upsert_company("smartrecruiters", "BoschGroup", db_path=db_file)
    engine = JobDiscoveryEngine(settings=Settings(), db_path=db_file)

    with patch.object(engine.registry, "ensure_seeded", return_value=0), \
         patch("src.discovery.engine.fetch_smartrecruiters_jobs",
               return_value=smartrecruiters.parse_smartrecruiters_postings(PAGE, "BoschGroup")) as fetch:
        jobs = engine.run_tier1_direct_apis(company_limit=5)

    fetch.assert_called_once_with("BoschGroup")  # identifier case preserved
    assert len(jobs) == 2


def test_companies_yaml_ships_smartrecruiters_and_existing_users_get_them(tmp_path: Path):
    from src.discovery.registry import DEFAULT_YAML_PATH

    shipped = yaml.safe_load(DEFAULT_YAML_PATH.read_text(encoding="utf-8"))
    assert "BoschGroup" in shipped["smartrecruiters"]

    # An existing user's registry (already populated) still picks up the new platform's companies.
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    upsert_company("greenhouse", "stripe", db_path=db_file)
    added = CompanyRegistry(db_path=db_file).ensure_seeded()
    sr = {r["slug"] for r in list_companies(platform="smartrecruiters", db_path=db_file)}
    assert added > 0 and set(shipped["smartrecruiters"]) <= sr


def test_jobspy_default_sources_exclude_google(monkeypatch):
    import sys
    import types

    from src.discovery import jobspy_adapter

    calls = []
    fake = types.ModuleType("jobspy")
    fake.scrape_jobs = lambda **kw: calls.append(kw["site_name"]) or None
    monkeypatch.setitem(sys.modules, "jobspy", fake)

    jobspy_adapter.fetch_jobspy_jobs(["Sales Manager"], locations="India", include_remote=True)

    assert calls and all("google" not in sites for sites in calls)
