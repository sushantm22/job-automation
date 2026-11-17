from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT, load_env_file, resolve_database_path

# Resolved once at import from DATABASE_PATH (.env or environment) so every module that
# defaults to DB_PATH — CLI, discovery engine, registry, Notion sync — uses the same ledger.
load_env_file()
DB_PATH = resolve_database_path(os.getenv("DATABASE_PATH"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source TEXT,
    company TEXT,
    title TEXT,
    location TEXT,
    url TEXT UNIQUE,
    description TEXT,
    posted_at TEXT,
    discovered_at TEXT,
    match_score INTEGER,
    match_reason TEXT,
    status TEXT DEFAULT 'new',
    notion_page_id TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    started_at TEXT,
    submitted_at TEXT,
    adapter_used TEXT,
    llm_calls INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    result TEXT,
    error TEXT,
    screenshot_path TEXT
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(id),
    question TEXT,
    answer TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS answer_bank (
    id INTEGER PRIMARY KEY,
    question_norm TEXT UNIQUE,
    answer TEXT,
    field_type TEXT,
    approved INTEGER DEFAULT 0,
    last_used TEXT
);

-- First-seen tracking for undated listings (see discovery/freshness.py). A scope is a dataset
-- platform ("jobhive:workday") or one company of a live scraper ("successfactors|wipro limited").
-- baseline=1: listed when the scope was first read (old backlog, not added as jobs).
CREATE TABLE IF NOT EXISTS seen_listings (
    url TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    baseline INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seen_listings_scope ON seen_listings(scope);

CREATE TABLE IF NOT EXISTS company_registry (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT,
    status TEXT DEFAULT 'active',
    job_count INTEGER DEFAULT 0,
    discovered_via TEXT DEFAULT 'seed',
    last_checked_at TEXT,
    created_at TEXT,
    UNIQUE(platform, slug)
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path = DB_PATH) -> Path:
    connection = get_connection(db_path)
    try:
        connection.executescript(SCHEMA)
        # Columns added after the first release; ALTER fails harmlessly if they already exist.
        for column in ("notion_page_id TEXT", "closed_at TEXT", "notion_closed INTEGER DEFAULT 0", "closed_reason TEXT"):
            try:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass
        connection.commit()
    finally:
        connection.close()
    return db_path


def upsert_jobs(jobs: list[dict], db_path: Path = DB_PATH) -> int:
    connection = get_connection(db_path)
    inserted = 0
    try:
        for job in jobs:
            before = connection.total_changes
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO jobs (source, company, title, location, url, description, posted_at, discovered_at, match_score, match_reason, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
                ON CONFLICT(url) DO NOTHING
                """,
                (
                    job.get("source"),
                    job.get("company"),
                    job.get("title"),
                    job.get("location"),
                    job.get("url"),
                    job.get("description"),
                    job.get("posted_at"),
                    now,
                    job.get("match_score"),
                    job.get("match_reason"),
                ),
            )
            after = connection.total_changes
            inserted += max(0, after - before)
        connection.commit()
    finally:
        connection.close()
    return inserted


def list_jobs(status: str | None = None, db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    connection = get_connection(db_path)
    try:
        if status:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY discovered_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM jobs ORDER BY discovered_at DESC").fetchall()
        return rows
    finally:
        connection.close()


def close_missing_jobs(source: str, open_urls: set[str], db_path: Path = DB_PATH) -> int:
    """
    Closed-job tracking: marks jobs from `source` that are no longer in its latest complete
    snapshot. Sets closed_at; the status changes to 'closed' only while it is still 'new', so a
    job the user has moved on (reviewing/applied) keeps their status. Returns the number closed.
    """
    now = datetime.now(timezone.utc).isoformat()
    connection = get_connection(db_path)
    try:
        rows = connection.execute(
            "SELECT id, url FROM jobs WHERE source = ? AND closed_at IS NULL", (source,)
        ).fetchall()
        gone = [(now, r["id"]) for r in rows if r["url"] not in open_urls]
        connection.executemany(
            "UPDATE jobs SET closed_at = ?, closed_reason = 'gone', "
            "status = CASE WHEN status = 'new' THEN 'closed' ELSE status END WHERE id = ?",
            gone,
        )
        connection.commit()
        return len(gone)
    finally:
        connection.close()


def reopen_jobs(urls: set[str], db_path: Path = DB_PATH) -> int:
    """
    Clears closed_at for jobs closed as 'gone' that are seen again (any source). Jobs closed as
    'too_old' never reopen. Returns the number reopened.
    """
    if not urls:
        return 0
    connection = get_connection(db_path)
    try:
        rows = connection.execute(
            "SELECT id, url FROM jobs WHERE closed_at IS NOT NULL "
            "AND (closed_reason IS NULL OR closed_reason = 'gone')"
        ).fetchall()
        back = [(r["id"],) for r in rows if r["url"] in urls]
        connection.executemany(
            "UPDATE jobs SET closed_at = NULL, closed_reason = NULL, "
            "status = CASE WHEN status = 'closed' THEN 'new' ELSE status END WHERE id = ?",
            back,
        )
        connection.commit()
        return len(back)
    finally:
        connection.close()


def admit_first_seen(scope_urls: dict[str, set[str]], db_path: Path = DB_PATH) -> set[str]:
    """
    First-seen tracking. For each scope: if it has never been read, record all its URLs as the
    baseline and admit none; otherwise record and admit only URLs not seen before (new listings).
    Returns the admitted URLs.
    """
    now = datetime.now(timezone.utc).isoformat()
    admitted: set[str] = set()
    connection = get_connection(db_path)
    try:
        for scope, urls in scope_urls.items():
            known = {r["url"] for r in connection.execute("SELECT url FROM seen_listings WHERE scope = ?", (scope,))}
            is_baseline = not known
            new = urls - known
            connection.executemany(
                "INSERT OR IGNORE INTO seen_listings (url, scope, first_seen, baseline) VALUES (?, ?, ?, ?)",
                [(u, scope, now, 1 if is_baseline else 0) for u in new],
            )
            if not is_baseline:
                admitted |= new
        connection.commit()
        return admitted
    finally:
        connection.close()


def close_stale_jobs(max_days: int, db_path: Path = DB_PATH, first_seen: bool = True) -> int:
    """
    Closes open jobs (reason 'too_old') that are past the age limit: a known posting date older
    than max_days, or, for first-seen sources, first seen more than max_days ago or never admitted
    as new (stored before first-seen tracking: old backlog). With first_seen=False (undated_jobs:
    include), undated jobs are never closed for age. Returns the number closed.
    """
    from .discovery.freshness import is_too_old, uses_first_seen

    if not max_days or max_days <= 0:
        return 0
    now = datetime.now(timezone.utc)
    connection = get_connection(db_path)
    try:
        admitted = {
            r["url"]: r["first_seen"]
            for r in connection.execute("SELECT url, first_seen FROM seen_listings WHERE baseline = 0")
        }
        rows = connection.execute(
            "SELECT id, url, source, posted_at FROM jobs WHERE closed_at IS NULL"
        ).fetchall()
        stale = []
        for r in rows:
            if r["posted_at"]:
                old = is_too_old(r["posted_at"], max_days, now)
            elif first_seen and uses_first_seen(r["source"] or ""):
                first_seen = admitted.get(r["url"])
                old = first_seen is None or is_too_old(first_seen, max_days, now)
            else:
                old = False
            if old:
                stale.append((now.isoformat(), r["id"]))
        connection.executemany(
            "UPDATE jobs SET closed_at = ?, closed_reason = 'too_old', "
            "status = CASE WHEN status = 'new' THEN 'closed' ELSE status END WHERE id = ?",
            stale,
        )
        connection.commit()
        return len(stale)
    finally:
        connection.close()


def update_job_status(job_id: int, status: str, db_path: Path = DB_PATH) -> None:
    connection = get_connection(db_path)
    try:
        connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        connection.commit()
    finally:
        connection.close()


def upsert_company(
    platform: str,
    slug: str,
    name: str | None = None,
    status: str = "active",
    job_count: int = 0,
    discovered_via: str = "seed",
    db_path: Path = DB_PATH,
) -> bool:
    """Upsert a company into company_registry. Returns True if inserted as a new company."""
    clean_platform = platform.lower().strip()
    clean_slug = slug.strip() if platform.lower() == "smartrecruiters" else slug.lower().strip()
    display_name = name or clean_slug.replace("-", " ").replace("_", " ").title()
    now = datetime.now(timezone.utc).isoformat()

    connection = get_connection(db_path)
    try:
        existing = connection.execute(
            "SELECT id FROM company_registry WHERE platform = ? AND slug = ?",
            (clean_platform, clean_slug),
        ).fetchone()

        connection.execute(
            """
            INSERT INTO company_registry (platform, slug, name, status, job_count, discovered_via, last_checked_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, slug) DO UPDATE SET
                name=coalesce(excluded.name, company_registry.name),
                status=excluded.status,
                job_count=case when excluded.job_count > 0 then excluded.job_count else company_registry.job_count end,
                last_checked_at=excluded.last_checked_at
            """,
            (clean_platform, clean_slug, display_name, status, job_count, discovered_via, now, now),
        )
        connection.commit()
        return existing is None
    finally:
        connection.close()


def list_companies(
    platform: str | None = None,
    status: str | None = "active",
    limit: int | None = None,
    db_path: Path = DB_PATH,
    stale_first: bool = False,
) -> list[sqlite3.Row]:
    """
    Lists registry companies. By default the biggest boards come first; with
    `stale_first=True` the least-recently-checked boards come first, so a limited
    batch rotates through the whole registry across runs instead of re-polling the same top N.
    """
    connection = get_connection(db_path)
    try:
        query = "SELECT * FROM company_registry WHERE 1=1"
        params: list[Any] = []
        if platform:
            query += " AND platform = ?"
            params.append(platform.lower().strip())
        if status:
            query += " AND status = ?"
            params.append(status.lower().strip())
        if stale_first:
            # NULL last_checked_at sorts first in SQLite ASC, so never-checked boards lead.
            query += " ORDER BY last_checked_at ASC, job_count DESC, name ASC"
        else:
            query += " ORDER BY job_count DESC, name ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return connection.execute(query, params).fetchall()
    finally:
        connection.close()


def mark_company_checked(
    platform: str,
    slug: str,
    job_count: int | None = None,
    db_path: Path = DB_PATH,
    status: str | None = None,
) -> None:
    """
    Stamps last_checked_at after a Tier 1 poll, optionally updating job_count and status.
    The company name is never touched (upsert_company would overwrite it with a slug-derived name).
    """
    now = datetime.now(timezone.utc).isoformat()
    sets, params = ["last_checked_at = ?"], [now]
    if job_count is not None:
        sets.append("job_count = ?")
        params.append(int(job_count))
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    connection = get_connection(db_path)
    try:
        connection.execute(
            f"UPDATE company_registry SET {', '.join(sets)} WHERE platform = ? AND slug = ?",
            (*params, platform.lower().strip(), slug),
        )
        connection.commit()
    finally:
        connection.close()


def get_company_stats(db_path: Path = DB_PATH) -> dict[str, Any]:
    connection = get_connection(db_path)
    try:
        total = connection.execute("SELECT count(*) FROM company_registry").fetchone()[0]
        active_total = connection.execute(
            "SELECT count(*) FROM company_registry WHERE status = 'active'"
        ).fetchone()[0]
        by_platform_rows = connection.execute(
            "SELECT platform, count(*) as cnt, sum(job_count) as total_jobs FROM company_registry WHERE status = 'active' GROUP BY platform"
        ).fetchall()
        by_status_rows = connection.execute(
            "SELECT status, count(*) as cnt FROM company_registry GROUP BY status"
        ).fetchall()
        by_source_rows = connection.execute(
            "SELECT discovered_via, count(*) as cnt FROM company_registry WHERE status = 'active' GROUP BY discovered_via"
        ).fetchall()

        return {
            "total_companies": total,
            "active_companies": active_total,
            "by_platform": {r["platform"]: {"count": r["cnt"], "jobs": r["total_jobs"] or 0} for r in by_platform_rows},
            "by_status": {r["status"]: r["cnt"] for r in by_status_rows},
            "by_source": {r["discovered_via"]: r["cnt"] for r in by_source_rows},
        }
    finally:
        connection.close()


def reset_db(db_path: Path = DB_PATH) -> dict[str, int]:
    """Clears all jobs and applications from the local SQLite database while preserving tables and schema."""
    connection = get_connection(db_path)
    try:
        jobs_count = connection.execute("SELECT count(*) FROM jobs").fetchone()[0]
        apps_count = connection.execute("SELECT count(*) FROM applications").fetchone()[0]
        connection.execute("DELETE FROM applications")
        connection.execute("DELETE FROM jobs")
        connection.execute("DELETE FROM seen_listings")  # clean slate: baselines are re-established
        try:
            connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('jobs', 'applications')")
        except sqlite3.OperationalError:
            pass
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
        # The JobHive cache marks dataset files as "already processed"; after a reset they aren't.
        Path(f"{db_path}.jobhive-cache.json").unlink(missing_ok=True)
        return {"jobs_deleted": jobs_count, "applications_deleted": apps_count}
    finally:
        connection.close()
