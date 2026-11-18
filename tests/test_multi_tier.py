from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from src.config import Settings
from src.db import init_db
from src.discovery.base import JobRecord
from src.discovery.apify_adapter import (
    fetch_apify_naukri_jobs,
    parse_apify_naukri_items,
)
from src.discovery.engine import JobDiscoveryEngine
from src.discovery.firecrawl_adapter import (
    fetch_firecrawl_portal_jobs,
    parse_firecrawl_extracted_jobs,
)


def test_parse_apify_naukri_items_normalizes_records():
    raw_items = [
        {
            "jobTitle": "Lead Python Developer",
            "companyName": "TechCorp India",
            "jobLocation": ["Bengaluru", "Remote"],
            "jobUrl": "https://www.naukri.com/job-listings-12345",
            "jobDescription": "<p>Looking for a Senior Python Developer with FastAPI & Docker.</p>",
            "postedDate": "2026-11-10",
        },
        {
            "title": "Backend QA / SDET",
            "company": "Fintech Solutions",
            "location": "Pune",
            "url": "https://www.naukri.com/job-listings-67890",
            "description": "SDET with automated testing & Python.",
        },
    ]

    records = parse_apify_naukri_items(raw_items)

    assert len(records) == 2
    assert records[0].source == "apify:naukri"
    assert records[0].title == "Lead Python Developer"
    assert records[0].company == "TechCorp India"
    assert "Bengaluru" in records[0].location
    assert records[0].url == "https://www.naukri.com/job-listings-12345"
    assert "FastAPI" in records[0].description

    assert records[1].title == "Backend QA / SDET"
    assert records[1].company == "Fintech Solutions"


def test_fetch_apify_naukri_missing_token_graceful():
    # Zero human intervention: When no token is configured, safely return empty list without crash or prompt
    res = fetch_apify_naukri_jobs(
        keywords=["python"],
        locations=["India"],
        api_token="",
    )
    assert res == []


def test_parse_firecrawl_extracted_jobs_structured_and_fallback():
    # 1. Structured JSON extraction test
    structured_data = {
        "extract": {
            "jobs": [
                {
                    "title": "Staff Software Engineer - Infrastructure",
                    "company": "Google",
                    "location": "Bengaluru, Karnataka, India",
                    "url": "https://www.google.com/about/careers/applications/jobs/results/999",
                    "description": "Design and scale large distributed backend systems.",
                }
            ]
        }
    }

    records = parse_firecrawl_extracted_jobs(structured_data, default_company="Google")
    assert len(records) == 1
    assert records[0].source == "firecrawl:google"
    assert records[0].title == "Staff Software Engineer - Infrastructure"
    assert records[0].company == "Google"
    assert records[0].url == "https://www.google.com/about/careers/applications/jobs/results/999"

    # 2. Markdown link fallback test
    markdown_data = {
        "markdown": """
        ## Open Roles at Apple
        - [Senior Python Software Engineer](https://jobs.apple.com/en-in/details/111/senior-engineer)
        - [Privacy Policy](https://www.apple.com/legal/privacy)
        """
    }
    fallback_records = parse_firecrawl_extracted_jobs(markdown_data, default_company="Apple")
    assert len(fallback_records) == 1
    assert fallback_records[0].source == "firecrawl:apple"
    assert fallback_records[0].title == "Senior Python Software Engineer"
    assert "jobs.apple.com" in fallback_records[0].url


def test_fetch_firecrawl_missing_key_graceful():
    # Zero human intervention: When no key is configured, safely return empty list without crash or prompt
    res = fetch_firecrawl_portal_jobs(api_key="")
    assert res == []


def test_engine_orchestration_and_deduplication(tmp_path):
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    settings = Settings(
        tier1_direct_apis=True,
        tier2_jobspy=True,
        tier3_apify=True,
        tier4_firecrawl=True,
        search_keywords=["python"],
        locations=["Remote", "Bengaluru", "Pune"],
    )

    engine = JobDiscoveryEngine(settings=settings, db_path=db_file)

    # Mock all 4 tiers
    job_dup = JobRecord(
        source="greenhouse",
        company="Stripe",
        title="Python Software Engineer",
        location="Remote",
        url="https://boards.greenhouse.io/stripe/jobs/1",
        description="Python backend",
    )
    job_t2 = JobRecord(
        source="jobspy:linkedin",
        company="LinkedIn Hire",
        title="Python Dev",
        location="Bengaluru",
        url="https://www.linkedin.com/jobs/view/2",
        description="FastAPI",
    )
    job_t3 = JobRecord(
        source="apify:naukri",
        company="Naukri Corp",
        title="Python Lead Engineer",
        location="Pune",
        url="https://www.naukri.com/job-3",
        description="Python & Django",
    )
    job_t4 = JobRecord(
        source="firecrawl:google",
        company="Google",
        title="Staff Python Engineer",
        location="Bengaluru",
        url="https://careers.google.com/job-4",
        description="Go & Python",
    )

    with patch.object(engine, "run_tier1_direct_apis", return_value=[job_dup]), \
         patch.object(engine, "run_tier2_jobspy", return_value=[job_t2]), \
         patch.object(engine, "run_tier3_apify", return_value=[job_t3]), \
         patch.object(engine, "run_tier4_firecrawl", return_value=[job_t4]):

        result = engine.execute_all_tiers(auto_harvest=False)

        assert result["total_discovered"] == 4
        assert result["net_new_inserted"] == 4
        assert result["duplicates_prevented"] == 0

        # Execute again with the exact same jobs -> all 4 should be recognized as duplicates!
        second_result = engine.execute_all_tiers(auto_harvest=False)
        assert second_result["total_discovered"] == 4
        assert second_result["net_new_inserted"] == 0
        assert second_result["duplicates_prevented"] == 4


def test_engine_auto_harvesting(tmp_path):
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    settings = Settings(
        tier1_direct_apis=False,  # Skip tier 1 for this test
        tier2_jobspy=True,
        tier3_apify=False,
        tier4_firecrawl=False,
        search_keywords=["python"],
    )

    engine = JobDiscoveryEngine(settings=settings, db_path=db_file)

    # Job from an aggregator that links directly to a Greenhouse company board
    aggregator_job = JobRecord(
        source="jobspy:indeed",
        company="Cool Startup",
        title="Senior Python Engineer",
        location="India",
        url="https://job-boards.greenhouse.io/coolstartup/jobs/987654",
        description="Apply at our greenhouse board",
    )

    with patch.object(engine, "run_tier2_jobspy", return_value=[aggregator_job]), \
         patch("src.discovery.registry.probe_company_board") as mock_probe:

        mock_probe.return_value = {
            "valid": True,
            "status": "active",
            "name": "Cool Startup",
            "job_count": 12,
            "platform": "greenhouse",
            "slug": "coolstartup",
        }

        result = engine.execute_all_tiers(auto_harvest=True)

        assert result["total_discovered"] == 1
        assert result["harvested_companies"] == 1

        # Check SQLite company_registry
        conn = sqlite3.connect(db_file)
        row = conn.execute("SELECT slug, platform, status FROM company_registry WHERE slug = 'coolstartup'").fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "coolstartup"
        assert row[1] == "greenhouse"
        assert row[2] == "active"



def test_apify_skipped_when_jobspy_has_naukri(tmp_path):
    """Tier 3 Apify should be skipped when JobSpy already returned Naukri results."""
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    settings = Settings(
        tier1_direct_apis=False,
        tier2_jobspy=True,
        tier3_apify=True,
        tier4_firecrawl=False,
        search_keywords=["SDET"],
        locations=["India"],
        apify_api_token="fake-token",
    )

    engine = JobDiscoveryEngine(settings=settings, db_path=db_file)

    naukri_job = JobRecord(
        source="naukri",
        company="InfoTech",
        title="SDET",
        location="India",
        url="https://www.naukri.com/job-999",
        description="Testing role",
    )

    with patch.object(engine, "run_tier2_jobspy", return_value=[naukri_job]) as mock_t2, \
         patch.object(engine, "run_tier3_apify") as mock_t3:

        result = engine.execute_all_tiers(auto_harvest=False)

        # Tier 2 should have run
        mock_t2.assert_called_once()
        # Tier 3 should NOT have run because JobSpy returned Naukri results
        mock_t3.assert_not_called()
        assert result["tier_counts"]["tier3_apify"] == 0


def test_apify_fires_when_no_naukri_from_jobspy(tmp_path):
    """Tier 3 Apify should fire when JobSpy returned 0 Naukri results."""
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    settings = Settings(
        tier1_direct_apis=False,
        tier2_jobspy=True,
        tier3_apify=True,
        tier4_firecrawl=False,
        search_keywords=["SDET"],
        locations=["India"],
        apify_api_token="fake-token",
    )

    engine = JobDiscoveryEngine(settings=settings, db_path=db_file)

    linkedin_job = JobRecord(
        source="jobspy:linkedin",
        company="SomeCompany",
        title="SDET",
        location="Bengaluru",
        url="https://linkedin.com/jobs/view/123",
        description="QA role",
    )

    apify_job = JobRecord(
        source="apify:naukri",
        company="NaukriCorp",
        title="SDET Lead",
        location="India",
        url="https://naukri.com/job-abc",
        description="Lead SDET",
    )

    with patch.object(engine, "run_tier2_jobspy", return_value=[linkedin_job]), \
         patch.object(engine, "run_tier3_apify", return_value=[apify_job]) as mock_t3:

        result = engine.execute_all_tiers(auto_harvest=False)

        # Tier 3 SHOULD have fired since no Naukri results from JobSpy
        mock_t3.assert_called_once()
        assert result["tier_counts"]["tier3_apify"] == 1


def test_firecrawl_skips_covered_companies(tmp_path):
    """Tier 4 Firecrawl should skip companies already found in previous tiers."""
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    settings = Settings(
        tier1_direct_apis=True,
        tier2_jobspy=False,
        tier3_apify=False,
        tier4_firecrawl=True,
        search_keywords=["SDET"],
        locations=["India"],
        firecrawl_api_key="fake-key",
        firecrawl_daily_budget=5,
    )

    engine = JobDiscoveryEngine(settings=settings, db_path=db_file)

    # Tier 1 already found a Google job
    google_job = JobRecord(
        source="greenhouse",
        company="Google",
        title="SDET",
        location="Bengaluru",
        url="https://boards.greenhouse.io/google/jobs/1",
        description="Testing at Google",
    )

    with patch.object(engine, "run_tier1_direct_apis", return_value=[google_job]), \
         patch("src.discovery.engine.fetch_firecrawl_portal_jobs") as mock_fc:

        mock_fc.return_value = []
        result = engine.execute_all_tiers(auto_harvest=False)

        # Verify covered_companies was passed with 'google' in it
        mock_fc.assert_called_once()
        call_kwargs = mock_fc.call_args.kwargs
        covered = call_kwargs.get("covered_companies")
        assert covered is not None
        assert "google" in covered


def test_firecrawl_budget_limits_portals():
    """Firecrawl should stop after exhausting the credit budget."""
    from src.discovery.firecrawl_adapter import fetch_firecrawl_portal_jobs

    portals = [
        {"name": f"Company{i}", "url": f"https://example{i}.com/careers"} for i in range(20)
    ]

    with patch("src.discovery.firecrawl_adapter.scrape_portal_with_firecrawl") as mock_scrape:
        mock_scrape.return_value = []
        fetch_firecrawl_portal_jobs(
            portals=portals,
            api_key="test-key",
            budget=3,
            covered_companies=set(),
        )
        # Should have only called scrape for 3 portals (budget=3), not all 20
        assert mock_scrape.call_count == 3


def test_load_enterprise_portals_from_yaml():
    """Enterprise portals should load dynamically from companies.yaml."""
    from src.discovery.firecrawl_adapter import load_enterprise_portals

    portals = load_enterprise_portals()
    assert isinstance(portals, list)
    assert len(portals) >= 4  # At least Google, Apple, Uber, Netflix
    names = [p["name"] for p in portals]
    assert "Google" in names
    assert "Apple" in names
    # All portals should have both name and url
    for p in portals:
        assert "name" in p
        assert "url" in p
        assert p["url"].startswith("http")
