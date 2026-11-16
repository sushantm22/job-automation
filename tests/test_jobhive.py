from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from src.config import Settings
from src.db import init_db, reset_db
from src.discovery import jobhive
from src.discovery.engine import JobDiscoveryEngine

ROWS = [
    {"title": "Senior Sales Manager", "company": "3M", "location": "IN, Bangalore Kar", "url": "https://3m.wd1.myworkdayjobs.com/job/1"},
    {"title": "Area Sales Manager", "company": "Abbott", "location": "Pune, Maharashtra, India", "url": "https://abbott.wd5.myworkdayjobs.com/job/2"},
    {"title": "Sales Manager", "company": "FedEx", "location": "Memphis, TN", "url": "https://fedex.wd1.myworkdayjobs.com/job/3"},
    {"title": "Sales Manager", "company": "Barclays", "location": "London, United Kingdom", "url": "https://barclays.wd3.myworkdayjobs.com/job/4"},
    {"title": "QA Lead", "company": "HPE", "location": "Bengaluru", "url": ""},  # no URL: dropped
]


def _parquet_bytes(rows=ROWS, description_chars: int = 10) -> bytes:
    import os

    buf = io.BytesIO()
    # Random hex doesn't compress, like real job descriptions (the bulk of the real files).
    descriptions = [os.urandom(description_chars // 2).hex() for _ in rows]
    table = pa.table({k: [r[k] for r in rows] for k in ("title", "company", "location", "url")}
                     | {"description": descriptions})
    pq.write_table(table, buf, row_group_size=2)
    return buf.getvalue()


class LocalFile(io.BytesIO):
    def __init__(self, data: bytes, last_modified: str = "Mon, 16 Nov 2026 14:52:41 GMT"):
        super().__init__(data)
        self.last_modified = last_modified
        self.bytes_read = len(data)


def test_keeps_only_india_rows_and_skips_us_state_codes():
    jobs = jobhive.fetch_jobhive_jobs(["workday"], opener=lambda url: LocalFile(_parquet_bytes()))

    assert [(j.company, j.location) for j in jobs] == [
        ("3M", "IN, Bangalore Kar"),
        ("Abbott", "Pune, Maharashtra, India"),
    ]  # "Memphis, TN" (Tennessee) and London are excluded; the row without a URL is dropped
    assert jobs[0].source == "jobhive:workday" and jobs[0].posted_at is None


def test_unchanged_file_with_same_settings_is_skipped(tmp_path: Path):
    cache = tmp_path / "jobs.db.jobhive-cache.json"
    opener = lambda url: LocalFile(_parquet_bytes())

    assert len(jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, opener=opener, cache_key="roles-A")) == 2
    assert jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, opener=opener, cache_key="roles-A") == []

    # Changed search settings: the cache doesn't apply, the file is read again.
    assert len(jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, opener=opener, cache_key="roles-B")) == 2
    # New daily snapshot (different Last-Modified): read again.
    newer = lambda url: LocalFile(_parquet_bytes(), last_modified="Tue, 17 Nov 2026 14:52:41 GMT")
    assert len(jobhive.fetch_jobhive_jobs(["workday"], cache_path=cache, opener=newer, cache_key="roles-B")) == 2


def test_one_failing_platform_does_not_stop_the_others():
    def opener(url):
        if "/oracle/" in url:
            raise OSError("CDN down")
        return LocalFile(_parquet_bytes())

    jobs = jobhive.fetch_jobhive_jobs(["oracle", "workday"], opener=opener)
    assert {j.source for j in jobs} == {"jobhive:workday"}


def test_http_range_file_reads_only_requested_columns(monkeypatch):
    data = _parquet_bytes(description_chars=200_000)  # ~1 MB file, almost all description
    requests_seen = []

    class Resp(io.BytesIO):
        def __init__(self, body, headers):
            super().__init__(body)
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        assert req.headers.get("User-agent", "").startswith("Automate-Applications/")
        if req.get_method() == "HEAD":
            return Resp(b"", {"Content-Length": str(len(data)), "Last-Modified": "Mon, 16 Nov 2026"})
        start, end = map(int, req.headers["Range"].removeprefix("bytes=").split("-"))
        requests_seen.append((start, end))
        return Resp(data[start:end + 1], {})

    monkeypatch.setattr(jobhive.request, "urlopen", fake_urlopen)
    jobs = jobhive.fetch_jobhive_jobs(["workday"])  # default opener: HTTPRangeFile

    assert len(jobs) == 2 and requests_seen
    fetched = sum(end - start + 1 for start, end in requests_seen)
    # pyarrow reads a fixed ~64 KB at the end of the file (the footer); beyond that only the
    # small columns we asked for. The large "description" column is never downloaded.
    assert fetched < len(data) * 0.1


def test_engine_runs_jobhive_in_tier1_and_reset_db_clears_its_cache(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    settings = Settings(jobhive_platforms=["workday"], notion_enabled=False,
                        search_keywords=["Sales Manager"], locations=["India", "Remote"])
    engine = JobDiscoveryEngine(settings=settings, db_path=db_file)

    with patch.object(engine, "run_tier1_direct_apis", return_value=[]), \
         patch("src.discovery.engine.fetch_jobhive_jobs",
               side_effect=lambda **kw: jobhive.fetch_jobhive_jobs(**kw, opener=lambda u: LocalFile(_parquet_bytes()))):
        result = engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)

    assert result["tier_counts"]["tier1_jobhive"] == 2
    assert result["net_new_inserted"] == 2  # both India sales jobs pass the role filter
    cache = Path(f"{db_file}.jobhive-cache.json")
    assert json.loads(cache.read_text())["stamps"] == {"workday": "Mon, 16 Nov 2026 14:52:41 GMT"}

    reset_db(db_path=db_file)
    assert not cache.exists()


def test_jobhive_can_be_disabled(tmp_path: Path):
    db_file = tmp_path / "jobs.db"
    init_db(db_file)
    engine = JobDiscoveryEngine(settings=Settings(jobhive_enabled=False, notion_enabled=False), db_path=db_file)
    with patch.object(engine, "run_tier1_direct_apis", return_value=[]), \
         patch.object(engine, "run_tier1_jobhive") as hive:
        engine.execute_all_tiers(selected_tiers=[1], auto_harvest=False)
    hive.assert_not_called()
