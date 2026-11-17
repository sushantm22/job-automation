"""Freshness: age limit, first-seen tracking for undated listings, stale closing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from src.config import Settings
from src.db import admit_first_seen, close_stale_jobs, get_connection, init_db, reopen_jobs, reset_db, upsert_jobs
from src.discovery.base import JobRecord
from src.discovery.engine import JobDiscoveryEngine
from src.discovery.freshness import age_in_days, is_too_old, parse_posted_at

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def test_parse_posted_at_handles_every_source_format():
    assert parse_posted_at("2026-11-12T08:00:00Z").day == 12  # ISO with Z (Ashby, SmartRecruiters)
    assert parse_posted_at("2026-11-12").tzinfo is not None  # plain date (JobSpy)
    assert parse_posted_at(1763000000000).year == 2025  # epoch milliseconds (Lever)
    assert parse_posted_at("1763000000").year == 2025  # epoch seconds as text
    assert parse_posted_at(datetime(2026, 1, 1)).tzinfo is not None
    assert parse_posted_at("not a date") is None and parse_posted_at(None) is None


def test_age_limit_only_applies_to_known_dates():
    assert is_too_old("2026-10-01", 30, NOW) is True
    assert is_too_old("2026-11-01", 30, NOW) is False
    assert is_too_old(None, 30, NOW) is False  # unknown dates are never "too old"
    assert is_too_old("2020-01-01", 0, NOW) is False  # 0 = no limit
    assert round(age_in_days("2026-11-17T12:00:00+00:00", NOW)) == 1


def test_first_seen_baseline_then_only_new_listings(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    assert admit_first_seen({"jobhive:workday": {"a", "b"}}, db_path=db) == set()  # first read: baseline
    assert admit_first_seen({"jobhive:workday": {"a", "b", "c"}}, db_path=db) == {"c"}  # c is new
    assert admit_first_seen({"jobhive:workday": {"a", "b", "c"}}, db_path=db) == set()  # nothing new
    # A different scope (another company) gets its own baseline.
    assert admit_first_seen({"successfactors|wipro limited": {"w1"}}, db_path=db) == set()


def _job(url, source="jobhive:workday", posted_at=None, company="3M"):
    return JobRecord(source=source, company=company, title="Senior Sales Manager", location="Pune, India",
                     url=url, description="", posted_at=posted_at)


def test_engine_drops_old_dated_jobs_and_undated_backlog(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    settings = Settings(notion_enabled=False, jobhive_enabled=False, max_job_age_days=30,
                        search_keywords=["Sales Manager"], locations=["India"])
    engine = JobDiscoveryEngine(settings=settings, db_path=db)

    day1 = [_job("old", "jobhive:oracle", _days_ago(200)), _job("recent", "jobhive:oracle", _days_ago(3)),
            _job("wd-backlog-1"), _job("wd-backlog-2"), _job("lever", "lever", None)]
    with patch.object(engine, "run_tier1_direct_apis", return_value=day1):
        r1 = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    assert (r1["too_old_skipped"], r1["baseline_skipped"], r1["net_new_inserted"]) == (1, 2, 2)  # recent + lever

    day2 = day1[1:] + [_job("wd-new")]  # one Workday listing appeared overnight
    with patch.object(engine, "run_tier1_direct_apis", return_value=day2):
        r2 = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    assert r2["net_new_inserted"] == 1 and r2["baseline_skipped"] == 2

    conn = get_connection(db)
    urls = {r["url"] for r in conn.execute("SELECT url FROM jobs")}
    conn.close()
    assert urls == {"recent", "lever", "wd-new"}


def test_undated_include_mode_keeps_the_backlog(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    engine = JobDiscoveryEngine(settings=Settings(notion_enabled=False, jobhive_enabled=False, undated_jobs="include",
                                                  search_keywords=["Sales Manager"], locations=["India"]), db_path=db)
    with patch.object(engine, "run_tier1_direct_apis", return_value=[_job("wd-1"), _job("wd-2")]):
        r = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    assert r["baseline_skipped"] == 0 and r["net_new_inserted"] == 2


def test_close_stale_jobs_and_too_old_never_reopens(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    upsert_jobs([
        {"source": "linkedin", "title": "a", "url": "dated-old", "posted_at": _days_ago(45)},
        {"source": "linkedin", "title": "b", "url": "dated-new", "posted_at": _days_ago(2)},
        {"source": "linkedin", "title": "c", "url": "undated-other"},  # not a first-seen source: kept
        {"source": "jobhive:workday", "title": "d", "url": "wd-backlog"},  # stored before tracking: stale
        {"source": "jobhive:workday", "title": "e", "url": "wd-admitted"},
    ], db_path=db)
    admit_first_seen({"jobhive:workday": {"x"}}, db_path=db)  # baseline
    admit_first_seen({"jobhive:workday": {"x", "wd-admitted"}}, db_path=db)  # admitted as new today

    assert close_stale_jobs(30, db_path=db) == 2
    conn = get_connection(db)
    rows = {r["url"]: (r["closed_reason"], r["status"]) for r in conn.execute("SELECT * FROM jobs")}
    conn.close()
    assert rows["dated-old"] == ("too_old", "closed") and rows["wd-backlog"] == ("too_old", "closed")
    assert rows["dated-new"][0] is None and rows["wd-admitted"][0] is None and rows["undated-other"][0] is None

    assert reopen_jobs({"dated-old", "wd-backlog"}, db_path=db) == 0  # "too old" stays closed
    assert close_stale_jobs(30, db_path=db, first_seen=False) == 0  # include mode never closes undated


def test_reset_db_clears_first_seen_baselines(tmp_path: Path):
    db = tmp_path / "jobs.db"
    init_db(db)
    admit_first_seen({"jobhive:workday": {"a"}}, db_path=db)
    reset_db(db_path=db)
    assert admit_first_seen({"jobhive:workday": {"a", "b"}}, db_path=db) == set()  # baseline again


def test_prune_old_command_closes_and_updates_notion(tmp_path: Path, monkeypatch):
    import src.db
    from src.cli import app

    db = tmp_path / "jobs.db"
    init_db(db)
    upsert_jobs([{"source": "linkedin", "title": "a", "url": "old", "posted_at": _days_ago(90)}], db_path=db)
    monkeypatch.setattr(src.db, "DB_PATH", db)
    with patch("src.cli.load_settings", return_value=Settings(max_job_age_days=30, notion_database_id="d" * 32)), \
         patch("src.integrations.notion_client.sync_closed_status",
               return_value={"closed": 1, "reopened": 0, "left_alone": 0, "failed": 0}) as notion:
        result = CliRunner().invoke(app, ["prune-old"])

    assert result.exit_code == 0, result.output
    assert "Marked 1 jobs older than 30 days" in result.output
    assert notion.call_args.kwargs["db_path"] == db


def test_close_stale_jobs_closes_every_backlog_row_not_just_the_first(tmp_path: Path):
    # Regression: a loop variable shadowed the `first_seen` flag, so only the first undated
    # backlog row was closed (seen in the test folder: 1 of 1,122).
    db = tmp_path / "jobs.db"
    init_db(db)
    upsert_jobs([{"source": "jobhive:workday", "title": str(i), "url": f"wd-{i}"} for i in range(25)]
                + [{"source": "jobhive:oracle", "title": "o", "url": "or-1"}], db_path=db)
    assert close_stale_jobs(30, db_path=db) == 26
