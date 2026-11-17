"""Closed-job tracking for JobHive platforms (Workday etc.)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.config import Settings
from src.db import close_missing_jobs, get_connection, init_db, reopen_jobs, upsert_jobs
from src.discovery import jobhive
from src.discovery.base import JobRecord
from src.discovery.engine import JobDiscoveryEngine
from src.integrations import notion_client

WD = "jobhive:workday"


def _db(tmp_path: Path, urls=("u1", "u2", "u3"), source=WD) -> Path:
    db = tmp_path / "jobs.db"
    init_db(db)
    upsert_jobs([{"source": source, "title": f"Sales Manager {u}", "location": "Pune, India", "url": u} for u in urls],
                db_path=db)
    return db


def _rows(db: Path) -> dict[str, dict]:
    conn = get_connection(db)
    try:
        return {r["url"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
    finally:
        conn.close()


def test_jobs_missing_from_snapshot_are_closed_and_return_when_seen(tmp_path: Path):
    db = _db(tmp_path)
    assert close_missing_jobs(WD, {"u1"}, db_path=db) == 2
    rows = _rows(db)
    assert rows["u1"]["closed_at"] is None and rows["u1"]["status"] == "new"
    assert rows["u2"]["closed_at"] and rows["u2"]["status"] == "closed"

    assert close_missing_jobs(WD, {"u1"}, db_path=db) == 0  # already closed: not counted again
    assert reopen_jobs({"u2"}, db_path=db) == 1
    assert _rows(db)["u2"]["closed_at"] is None and _rows(db)["u2"]["status"] == "new"


def test_closing_keeps_the_users_own_status(tmp_path: Path):
    db = _db(tmp_path)
    conn = get_connection(db)
    conn.execute("UPDATE jobs SET status = 'applied' WHERE url = 'u2'")
    conn.commit()
    conn.close()

    close_missing_jobs(WD, set(), db_path=db)
    assert _rows(db)["u2"]["status"] == "applied" and _rows(db)["u2"]["closed_at"]


def test_other_sources_are_never_closed(tmp_path: Path):
    db = _db(tmp_path, source="keka")
    assert close_missing_jobs(WD, set(), db_path=db) == 0


class _Local:
    """Minimal opener result for fetch_jobhive_jobs: a parquet file with a Last-Modified stamp."""

    def __init__(self, urls, stamp):
        import io
        import pyarrow as pa
        import pyarrow.parquet as pq

        buf = io.BytesIO()
        pq.write_table(pa.table({"title": ["Sales Manager"] * len(urls), "company": ["3M"] * len(urls),
                                 "location": ["Pune, India"] * len(urls), "url": list(urls)}), buf)
        self.file = buf
        buf.seek(0)
        self.last_modified = stamp

    def __getattr__(self, name):
        return getattr(self.file, name)


def test_snapshot_that_shrinks_by_more_than_half_is_not_used_for_closing(tmp_path: Path):
    cache = tmp_path / "cache.json"
    snaps: dict = {}
    jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, snapshots=snaps,
                               opener=lambda u: _Local([f"u{i}" for i in range(10)], "day1"))
    assert snaps["workday"]["closable"] is True and len(snaps["workday"]["urls"]) == 10

    snaps = {}
    jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, snapshots=snaps,
                               opener=lambda u: _Local(["u0", "u1"], "day2"))  # 2 vs 10: broken?
    assert snaps["workday"]["closable"] is False
    assert json.loads(cache.read_text())["counts"]["workday"] == 10  # baseline not lowered

    snaps = {}
    jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, snapshots=snaps,
                               opener=lambda u: _Local([f"u{i}" for i in range(7)], "day3"))  # normal churn
    assert snaps["workday"]["closable"] is True


def test_engine_closes_missing_workday_jobs_but_not_ones_seen_live(tmp_path: Path):
    db = _db(tmp_path)  # u1, u2, u3 stored from an earlier Workday snapshot
    engine = JobDiscoveryEngine(settings=Settings(notion_enabled=False, jobhive_platforms=["workday"],
                                                  search_keywords=["Sales Manager"]), db_path=db)

    def fake_hive(**kw):
        kw["snapshots"]["workday"] = {"urls": {"u1"}, "closable": True}  # today's snapshot: only u1
        return []

    live = [JobRecord(source="keka", company="X", title="Sales Manager", location="Pune, India", url="u3",
                      description="")]  # u3 is still live elsewhere
    with patch.object(engine, "run_tier1_direct_apis", return_value=live), \
         patch("src.discovery.engine.fetch_jobhive_jobs", side_effect=fake_hive):
        result = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)

    rows = _rows(db)
    assert result["jobs_closed"] == 1 and rows["u2"]["closed_at"]
    assert rows["u1"]["closed_at"] is None and rows["u3"]["closed_at"] is None


def test_closed_jobs_are_not_pushed_to_notion_as_new_rows(tmp_path: Path):
    db = _db(tmp_path)
    close_missing_jobs(WD, {"u1"}, db_path=db)
    settings = Settings(search_keywords=["Sales Manager"], locations=["India"], exclude_keywords=[])
    pushed = []
    with patch.object(notion_client, "load_settings", return_value=settings), \
         patch.object(notion_client, "push_job_to_notion", side_effect=lambda job, **kw: pushed.append(job["url"]) or "pg"):
        notion_client.sync_jobs_to_notion(database_id="d" * 32, api_token="ntn_x", db_path=db)
    assert pushed == ["u1"]


def test_notion_status_follows_closing_but_never_overwrites_user_progress(tmp_path: Path):
    db = _db(tmp_path)
    conn = get_connection(db)
    for url, page in (("u1", "p1"), ("u2", "p2"), ("u3", "p3")):
        conn.execute("UPDATE jobs SET notion_page_id = ? WHERE url = ?", (page, url))
    conn.commit()
    conn.close()
    close_missing_jobs(WD, set(), db_path=db)  # all three closed

    notion_status = {"p1": "New", "p2": "Applied", "p3": "Reviewing"}
    changes = []
    with patch.object(notion_client, "_page_status", side_effect=lambda pid, *a: notion_status[pid]), \
         patch.object(notion_client, "_set_page_status", side_effect=lambda pid, st, *a: changes.append((pid, st))):
        res = notion_client.sync_closed_status(api_token="ntn_x", db_path=db)
        assert sorted(changes) == [("p1", "Closed"), ("p3", "Closed")]  # "Applied" untouched
        assert res == {"closed": 2, "reopened": 0, "left_alone": 1, "failed": 0}

        # Nothing left to do on a second pass.
        changes.clear()
        notion_client.sync_closed_status(api_token="ntn_x", db_path=db)
        assert changes == []

        # u1 reappears: its Notion row goes back to New (only because it is still "Closed").
        reopen_jobs({"u1"}, db_path=db)
        notion_status["p1"] = "Closed"
        notion_client.sync_closed_status(api_token="ntn_x", db_path=db)
        assert changes == [("p1", "New")]
