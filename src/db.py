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
        try:
            connection.execute("ALTER TABLE jobs ADD COLUMN notion_page_id TEXT")
        except sqlite3.OperationalError:
            pass  # Already exists
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
        try:
            connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('jobs', 'applications')")
        except sqlite3.OperationalError:
            pass
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
        return {"jobs_deleted": jobs_count, "applications_deleted": apps_count}
    finally:
        connection.close()
