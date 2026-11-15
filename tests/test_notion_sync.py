from __future__ import annotations

import sqlite3
from unittest.mock import patch, MagicMock

import pytest
from src.db import init_db, get_connection
from src.integrations.notion_client import (
    clean_notion_id,
    format_job_properties,
    sync_jobs_to_notion,
)


def test_clean_notion_id():
    # Full URL
    url = "https://www.notion.so/myworkspace/Automated-Jobs-36078d50a2bd45738df03165997b325b?v=123"
    assert clean_notion_id(url) == "36078d50a2bd45738df03165997b325b"

    # UUID with hyphens
    uuid_str = "36078d50-a2bd-4573-8df0-3165997b325b"
    assert clean_notion_id(uuid_str) == "36078d50a2bd45738df03165997b325b"

    # Plain 32-char hex
    assert clean_notion_id("36078d50a2bd45738df03165997b325b") == "36078d50a2bd45738df03165997b325b"


def test_format_job_properties():
    job = {
        "title": "Lead SDET - Test Infrastructure",
        "company": "Netflix",
        "location": "Remote, India",
        "source": "firecrawl:netflix",
        "url": "https://explore.jobs.netflix.net/careers/job/12345",
        "match_score": 92,
        "status": "new",
        "discovered_at": "2026-11-12T04:00:00Z",
    }

    props = format_job_properties(job)

    assert props["Role Title"]["title"][0]["text"]["content"] == "Lead SDET - Test Infrastructure"
    assert props["Company"]["select"]["name"] == "Netflix"
    assert props["Source"]["select"]["name"] == "Netflix"
    assert props["Apply URL"]["url"] == "https://explore.jobs.netflix.net/careers/job/12345"
    assert props["Match Score"]["number"] == 92
    assert props["Status"]["select"]["name"] == "New"
    assert props["Discovered Date"]["date"]["start"] == "2026-11-12"


def test_sync_jobs_missing_token_or_db_graceful(tmp_path):
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    res = sync_jobs_to_notion(database_id="", api_token="", db_path=db_file)
    assert res == {"synced": 0, "failed": 0, "skipped": 0}


def test_sync_jobs_to_notion_updates_sqlite(tmp_path):
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    conn = get_connection(db_file)
    conn.execute(
        """
        INSERT INTO jobs (source, company, title, location, url, description, status)
        VALUES ('greenhouse', 'Stripe', 'Senior SDET', 'Remote', 'https://boards.greenhouse.io/stripe/jobs/99', 'Desc', 'new')
        """
    )
    conn.commit()
    conn.close()

    with patch("src.integrations.notion_client.push_job_to_notion", return_value="notion-page-abc-123"):
        res = sync_jobs_to_notion(
            database_id="36078d50a2bd45738df03165997b325b",
            api_token="fake_token_ntn_123",
            db_path=db_file,
        )

        assert res["synced"] == 1
        assert res["failed"] == 0

        # Verify notion_page_id updated in SQLite
        conn = get_connection(db_file)
        row = conn.execute("SELECT notion_page_id FROM jobs WHERE url = 'https://boards.greenhouse.io/stripe/jobs/99'").fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "notion-page-abc-123"
