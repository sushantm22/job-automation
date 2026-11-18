"""Finding more jobs per role: job-board windows/paging, per-source age limits, the current JobHive
dataset, honest freshness counts, close-title suggestions and matcher fixes."""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.config import DEFAULT_JOBHIVE_PLATFORMS, Settings
from src.db import close_stale_jobs, get_connection, init_db, reset_db, upsert_jobs
from src.discovery import jobhive, jobspy_adapter
from src.discovery.base import JobRecord
from src.discovery.engine import JobDiscoveryEngine, drop_dataset_duplicates
from src.discovery.freshness import is_company_source, max_age_for
from src.scoring import related_title_candidates, title_matches_roles


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _job(url, source="linkedin", title="Category Manager", posted_at=None, company="Licious", location="Bengaluru, India"):
    return JobRecord(source=source, company=company, title=title, location=location, url=url,
                     description="", posted_at=posted_at)


# --- Job boards (Tier 2): window, query plan, LinkedIn pacing ------------------------------------

def _df(site, n, start=0):
    return pd.DataFrame([{"site": site, "company": f"C{i}", "title": "Category Manager", "location": "Mumbai, India",
                          "job_url": f"https://{site}.test/{i}", "date_posted": "2026-11-17"} for i in range(start, start + n)])


def test_location_plan_searches_india_once_instead_of_every_city():
    plan = jobspy_adapter.plan_location_queries
    assert plan(["India", "Remote", "Bengaluru", "Pune"]) == ["India"]
    assert plan(["Remote"]) == ["India"]
    assert plan(["Pune", "Mumbai", "Remote"]) == ["Pune", "Mumbai"]  # no "India": cities are searched


def test_one_india_search_per_role_linkedin_alone_and_remote_only_on_indeed():
    calls = []

    def scraper(**kw):
        calls.append(kw)
        return _df(kw["site_name"][0], 2)

    sleeps = []
    jobs = jobspy_adapter.fetch_jobspy_jobs(
        ["Category Manager", "Category Head"], ["India", "Bengaluru", "Remote"], results_wanted=100,
        hours_old=720, scraper=scraper, sleep=sleeps.append, linkedin_pause_seconds=15,
    )
    linkedin = [c for c in calls if c["site_name"] == ["linkedin"]]
    boards = [c for c in calls if "naukri" in c["site_name"]]
    remote = [c for c in calls if c.get("is_remote")]
    assert [c["search_term"] for c in linkedin] == ["Category Manager", "Category Head"]
    assert all(c["location"] == "India" and c["hours_old"] == 720 and c["results_wanted"] == 100 for c in linkedin)
    assert [c["site_name"] for c in boards] == [["indeed", "naukri", "glassdoor"]] * 2  # no Bengaluru repeat
    assert [c["site_name"] for c in remote] == [["indeed"], ["indeed"]]
    assert sleeps == [15]  # paced between the two LinkedIn searches
    assert jobs  # URLs repeat across the fake calls; results are de-duplicated
    assert len({j.url for j in jobs}) == len(jobs)


def test_linkedin_429_waits_a_minute_and_continues_once_from_where_it_stopped():
    li_log = logging.getLogger("jobspy.linkedin")
    calls, sleeps = [], []

    def scraper(**kw):
        calls.append(kw)
        if kw["site_name"] != ["linkedin"]:
            return _df("indeed", 1)
        if kw["offset"] == 0:
            li_log.error("response status code 429 (blocked: use a proxy)")
            return _df("linkedin", 10)
        return _df("linkedin", 30, start=kw["offset"])

    report: dict = {}
    jobs = jobspy_adapter.fetch_jobspy_jobs(["Category Manager"], ["India"], sites=["linkedin", "indeed"],
                                            results_wanted=40, scraper=scraper, sleep=sleeps.append, report=report)
    li_calls = [c for c in calls if c["site_name"] == ["linkedin"]]
    assert [(c["offset"], c["results_wanted"]) for c in li_calls] == [(0, 40), (10, 30)]
    assert sleeps == [jobspy_adapter.LINKEDIN_RETRY_WAIT_SECONDS]
    assert report["linkedin"] == {"complete": True, "jobs": 40}
    assert sum(1 for j in jobs if j.source == "linkedin") == 40


def test_linkedin_still_throttled_after_retry_is_reported_incomplete():
    li_log = logging.getLogger("jobspy.linkedin")

    def scraper(**kw):
        if kw["site_name"] == ["linkedin"]:
            li_log.error("response status code 429 (blocked: use a proxy)")
            return _df("linkedin", 10, start=kw["offset"])
        return _df("indeed", 1)

    report: dict = {}
    jobspy_adapter.fetch_jobspy_jobs(["Category Manager"], ["India"], sites=["linkedin", "indeed"],
                                     results_wanted=100, scraper=scraper, sleep=lambda s: None, report=report)
    assert report["linkedin"]["complete"] is False and report["linkedin"]["jobs"] == 20


def _engine(tmp_path, **overrides):
    db = tmp_path / "jobs.db"
    init_db(db)
    base = dict(notion_enabled=False, jobhive_enabled=False, search_keywords=["Category Manager"],
                locations=["India", "Remote"], exclude_keywords=["intern"])
    return JobDiscoveryEngine(settings=Settings(**{**base, **overrides}), db_path=db)


def test_first_search_looks_back_the_age_limit_then_only_since_the_last_completed_run(tmp_path: Path):
    engine = _engine(tmp_path)
    seen = []

    def fake(**kw):
        seen.append(kw)
        kw["report"].update({"linkedin": {"complete": True, "jobs": 5}, "others": {"complete": True, "jobs": 5}})
        return [_job("https://x.test/1")]

    with patch("src.discovery.engine.fetch_jobspy_jobs", side_effect=fake):
        engine.run_tier2_jobspy()
        assert (seen[0]["hours_old"], seen[0]["linkedin_hours_old"], seen[0]["results_wanted"]) == (720, 720, 100)

        # Pretend the last completed search was 2 days ago: only ~3 days are searched now.
        state_path = Path(f"{engine.db_path}.jobspy-state.json")
        state = json.loads(state_path.read_text())
        key = next(iter(state))
        state[key] = {"linkedin": _ago(2), "others": _ago(2)}
        state_path.write_text(json.dumps(state))
        engine.run_tier2_jobspy()
        assert 72 <= seen[1]["hours_old"] <= 73 and seen[1]["linkedin_hours_old"] == seen[1]["hours_old"]  # 2 days + 1 day overlap

        # New roles: a full window again.
        engine.settings.search_keywords = ["Category Manager", "Category Lead"]
        engine.run_tier2_jobspy()
        assert seen[2]["hours_old"] == 720

    reset_db(db_path=engine.db_path)
    assert not state_path.exists()


def test_rate_limited_linkedin_keeps_its_full_window_for_next_time(tmp_path: Path):
    engine = _engine(tmp_path)
    seen = []

    def fake(**kw):
        seen.append(kw)
        kw["report"].update({"linkedin": {"complete": False, "jobs": 10}, "others": {"complete": True, "jobs": 50}})
        return [_job("https://x.test/1")]

    with patch("src.discovery.engine.fetch_jobspy_jobs", side_effect=fake):
        engine.run_tier2_jobspy()
        engine.run_tier2_jobspy()
    assert seen[1]["hours_old"] == 25 and seen[1]["linkedin_hours_old"] == 720  # just ran: ~1h + 1 day overlap


def test_discover_uses_the_configured_results_per_search_by_default():
    from typer.testing import CliRunner

    from src.cli import app

    result_stub = {"tier_counts": {}, "total_discovered": 0, "net_new_inserted": 0, "duplicates_prevented": 0}
    with patch("src.cli.load_settings", return_value=Settings(search_keywords=["Category Manager"])), \
         patch("src.cli.init_db"), patch("src.cli.JobDiscoveryEngine") as engine_cls:
        engine_cls.return_value.execute_all_tiers.return_value = result_stub
        CliRunner().invoke(app, ["discover", "--tiers", "2"])
        assert engine_cls.return_value.execute_all_tiers.call_args.kwargs["results_per_board"] is None
        CliRunner().invoke(app, ["discover", "--tiers", "2", "--results-per-board", "25"])
        assert engine_cls.return_value.execute_all_tiers.call_args.kwargs["results_per_board"] == 25


# --- Age limits per source kind ----------------------------------------------------------------

def test_company_sites_get_the_longer_age_limit():
    assert is_company_source("jobhive:amazon") and is_company_source("greenhouse") and is_company_source("keka")
    assert not is_company_source("linkedin") and not is_company_source("apify:naukri")
    assert max_age_for("jobhive:amazon", 30, 60) == 60 and max_age_for("naukri", 30, 60) == 30
    assert max_age_for("jobhive:amazon", 30) == 30  # no company limit given: one limit for all


def test_45_day_old_company_job_is_kept_but_45_day_old_linkedin_job_is_not(tmp_path: Path):
    engine = _engine(tmp_path)
    tier1 = [_job("https://amazon.test/1", "jobhive:amazon", posted_at=_ago(45), company="Amazon")]
    tier2 = [_job("https://li.test/1", "linkedin", posted_at=_ago(45)), _job("https://li.test/2", "linkedin", posted_at=_ago(3))]
    with patch.object(engine, "run_tier1_direct_apis", return_value=tier1), \
         patch.object(engine, "run_tier2_jobspy", return_value=tier2):
        result = engine.execute_all_tiers(selected_tiers=[1, 2], auto_harvest=False)
    conn = get_connection(engine.db_path)
    urls = {r["url"] for r in conn.execute("SELECT url FROM jobs")}
    conn.close()
    assert urls == {"https://amazon.test/1", "https://li.test/2"}
    assert result["too_old_matching"] == 1


def test_close_stale_jobs_applies_each_sources_limit(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    upsert_jobs([
        {"source": "jobhive:amazon", "title": "a", "url": "co-45", "posted_at": _ago(45)},
        {"source": "jobhive:amazon", "title": "b", "url": "co-70", "posted_at": _ago(70)},
        {"source": "linkedin", "title": "c", "url": "li-45", "posted_at": _ago(45)},
    ], db_path=db)
    assert close_stale_jobs(30, db_path=db, company_max_days=60) == 2
    conn = get_connection(db)
    closed = {r["url"] for r in conn.execute("SELECT url FROM jobs WHERE closed_at IS NOT NULL")}
    conn.close()
    assert closed == {"co-70", "li-45"}


# --- JobHive: current dataset location, India by country code, retries, more sources ----------

class _LocalFile(io.BytesIO):
    def __init__(self, rows, last_modified="Wed, 18 Nov 2026 14:44:39 GMT"):
        buf = io.BytesIO()
        pq.write_table(pa.table({k: [r.get(k) for r in rows] for k in rows[0]}), buf)
        super().__init__(buf.getvalue())
        self.last_modified = last_modified
        self.bytes_read = len(buf.getvalue())


def test_default_sources_match_config_and_include_the_new_ones():
    assert list(DEFAULT_JOBHIVE_PLATFORMS) == jobhive.DEFAULT_PLATFORMS
    assert {"phenom", "amazon", "eightfold", "zoho_recruit", "smartrecruiters"} <= set(jobhive.DEFAULT_PLATFORMS)


def test_file_urls_come_from_the_manifest_with_a_canonical_fallback():
    manifest = {"by_ats": {"workday": {"parquet": "https://storage.stapply.ai/jobs/v1/workday/jobs.parquet"}}}
    urls = jobhive.platform_urls(["workday", "phenom"], manifest)
    assert urls["workday"] == "https://storage.stapply.ai/jobs/v1/workday/jobs.parquet"
    assert urls["phenom"] == "https://storage.stapply.ai/jobs/v1/phenom/jobs.parquet"
    assert "jobhive/v1" not in jobhive.BASE_URL and "jobhive/v1" not in jobhive.MANIFEST_URL


def test_manifest_follows_the_dataset_when_it_moves(monkeypatch):
    v1 = {"deprecated_prefixes": {"jobs/v1": {"manifest": "https://storage.stapply.ai/jobs/v2/manifest.json",
                                               "replaced_by": "jobs/v2"}}}
    v2 = {"by_ats": {"workday": {"parquet": "https://storage.stapply.ai/jobs/v2/workday/jobs.parquet"}}}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(jobhive.request, "urlopen",
                        lambda req, timeout=None: Resp(json.dumps(v2 if "/v2/" in req.full_url else v1).encode()))
    assert jobhive.load_manifest()["by_ats"]["workday"]["parquet"].endswith("/jobs/v2/workday/jobs.parquet")


def test_country_code_in_keeps_india_rows_without_a_place_name():
    rows = [
        {"title": "Category Manager", "company": "A", "location": "Remote", "url": "u1", "country_iso": "IN"},
        {"title": "Category Manager", "company": "B", "location": "Memphis, TN", "url": "u2", "country_iso": "US"},
        {"title": "Category Manager", "company": "C", "location": "Pune, India", "url": "u3", "country_iso": None},
    ]
    jobs = jobhive.fetch_jobhive_jobs(["phenom"], opener=lambda url: _LocalFile(rows), manifest={})
    assert [(j.company, j.source) for j in jobs] == [("A", "jobhive:phenom"), ("C", "jobhive:phenom")]


def test_temporary_server_errors_are_retried():
    rows = [{"title": "Category Manager", "company": "A", "location": "Mumbai", "url": "u1"}]
    attempts, sleeps = [], []

    def opener(url):
        attempts.append(url)
        if len(attempts) == 1:
            raise HTTPError(url, 500, "Internal Server Error", None, None)
        return _LocalFile(rows)

    jobs = jobhive.fetch_jobhive_jobs(["oracle"], opener=opener, manifest={}, sleep=sleeps.append)
    assert len(jobs) == 1 and sleeps == [jobhive.RETRY_DELAYS[0]] and len(attempts) == 2


def test_a_missing_file_is_not_retried():
    sleeps = []

    def opener(url):
        raise HTTPError(url, 404, "Not Found", None, None)

    assert jobhive.fetch_jobhive_jobs(["nosuch"], opener=opener, manifest={}, sleep=sleeps.append) == []
    assert sleeps == []


def test_dataset_rows_repeating_a_direct_board_job_on_the_same_ats_are_dropped():
    live = _job("https://jobs.lever.co/acme/1", "lever", company="Acme", location="Pune")
    copy = _job("https://jobs.lever.co/acme/1?lever-source=x", "jobhive:lever", company="Acme", location="Pune")
    other_ats = _job("https://acme.wd1.myworkdayjobs.com/1", "jobhive:workday", company="Acme", location="Pune")
    assert drop_dataset_duplicates([live, copy, other_ats]) == [live, other_ats]


def test_dataset_urls_are_not_sent_to_the_company_harvester(tmp_path: Path):
    engine = _engine(tmp_path)
    tier1 = [_job("https://boards.greenhouse.io/acme/jobs/1", "jobhive:greenhouse")]
    tier2 = [_job("https://boards.greenhouse.io/other/jobs/2", "linkedin")]
    with patch.object(engine, "run_tier1_direct_apis", return_value=tier1), \
         patch.object(engine, "run_tier2_jobspy", return_value=tier2), \
         patch.object(engine.registry, "harvest_from_urls", return_value=0) as harvest:
        engine.execute_all_tiers(selected_tiers=[1, 2], auto_harvest=True)
    assert harvest.call_args.args[0] == ["https://boards.greenhouse.io/other/jobs/2"]


# --- Honest freshness counts and close-title suggestions ----------------------------------------

def test_freshness_counts_are_reported_for_matching_jobs_only(tmp_path: Path):
    engine = _engine(tmp_path)
    tier1 = [
        _job("wd-1", "jobhive:workday", company="Electrolux"),               # matching, undated: baseline
        _job("wd-2", "jobhive:workday", title="Software Engineer"),          # not matching, undated
        _job("or-1", "jobhive:oracle", posted_at=_ago(200)),                 # matching, too old
        _job("or-2", "jobhive:oracle", title="Nurse", posted_at=_ago(200)),  # not matching, too old
    ]
    with patch.object(engine, "run_tier1_direct_apis", return_value=tier1):
        r = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    assert (r["too_old_skipped"], r["baseline_skipped"]) == (2, 2)  # every row
    assert (r["too_old_matching"], r["baseline_matching"]) == (1, 1)  # what the user cares about
    assert r["baseline_matching_by_source"] == {"jobhive:workday": 1}


def test_close_titles_from_job_boards_are_suggested(tmp_path: Path):
    engine = _engine(tmp_path)
    tier2 = [
        _job("l1", "linkedin", title="Category Lead"), _job("l2", "naukri", title="Category Lead"),
        _job("l3", "indeed", title="Category Buyer"), _job("l4", "linkedin", title="Category Manager"),
        _job("l5", "linkedin", title="Procurement Manager"),
    ]
    hive = [_job("w1", "jobhive:workday", title="Category Specialist")]  # dataset titles: not suggestions
    with patch.object(engine, "run_tier1_direct_apis", return_value=hive), \
         patch.object(engine, "run_tier2_jobspy", return_value=tier2):
        r = engine.execute_all_tiers(selected_tiers=[1, 2], auto_harvest=False)
    assert r["related_titles"] == [("Category Lead", 2), ("Category Buyer", 1)]


def test_related_title_candidates_ranks_by_shared_field_words():
    roles = ["Category Manager", "Sr manager - category marketing", "Category Head"]
    titles = ["Marketing Manager", "Category Lead", "Category Lead", "Senior Category Manager", "Intern - Category", "Sales Head"]
    assert related_title_candidates(titles, roles, exclude=["intern"]) == [("Category Lead", 2), ("Marketing Manager", 1)]


# --- Matcher fixes ------------------------------------------------------------------------------

@pytest.mark.parametrize("title,roles,expected", [
    ("Manager-Product Category (Kitchen or Home Appliances)", ["Category Manager"], True),  # unspaced hyphen
    ("Manager – Sales, West", ["Sales Manager"], True),                                     # rest ends at ","
    ("VP – Head of Category", ["Category Head"], True),                                     # nested segment
    ("Director, Head of Sales (North)", ["Sales Head"], True),
    ("Lead-QA", ["QA Lead"], True),
    ("Category Head-Steam & Heat", ["Category Head"], True),
    ("E-Commerce Category Manager", ["Category Manager"], True),                            # e-commerce intact
    ("Walk-in Interview - Category Manager", ["Category Manager"], True),
    ("Manager, Sales Operations", ["Sales Manager"], False),
    ("Head of Category & Digital Merchandising", ["Category Head"], False),                 # = category merchandising
])
def test_matcher_reads_more_title_formats(title, roles, expected):
    assert title_matches_roles(title, roles) is expected


def test_discover_summary_shows_matching_freshness_and_close_titles_safely():
    from typer.testing import CliRunner

    from src.cli import app

    stub = {"tier_counts": {}, "total_discovered": 3, "net_new_inserted": 1, "duplicates_prevented": 0,
            "too_old_matching": 2, "baseline_matching": 15,
            "baseline_matching_by_source": {"jobhive:workday": 13, "jobhive:successfactors": 2},
            "jobspy_window_hours": {"others": 720, "linkedin": 720},
            "related_titles": [("Category Lead [Remote]", 6), ("Category Buyer", 3)]}
    with patch("src.cli.load_settings", return_value=Settings(search_keywords=["Category Manager"], notion_enabled=False)), \
         patch("src.cli.init_db"), patch("src.cli.JobDiscoveryEngine") as engine_cls, patch("src.onboard_steps.mark_step"):
        engine_cls.return_value.execute_all_tiers.return_value = stub
        result = CliRunner().invoke(app, ["discover", "--tiers", "2"], terminal_width=400)
    out = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert "searched jobs posted in the last 30 days" in out
    assert "held back 15 matching SuccessFactors/Workday jobs" in out
    assert "Category Lead [Remote] (6), Category Buyer (3)" in out  # "[...]" is not eaten as markup
