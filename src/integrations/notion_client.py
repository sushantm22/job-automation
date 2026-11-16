from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib import request, error

from ..config import Settings, load_settings
from ..db import DB_PATH, get_connection
from ..utils.net import never_reached_server

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


# Select-option colors the Notion API accepts (anything else is a 400 validation_error).
NOTION_SELECT_COLORS = {"default", "gray", "brown", "orange", "yellow", "green", "blue", "purple", "pink", "red"}


# Waits before retrying a request that never reached Notion (DNS lookup failed / connection refused).
NETWORK_RETRY_DELAYS = (1.0, 3.0)


def _send_json(req: request.Request, timeout: float) -> dict[str, Any]:
    """Sends a Notion API request, retrying briefly if the network was momentarily unavailable."""
    for attempt in range(len(NETWORK_RETRY_DELAYS) + 1):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (error.URLError, OSError) as err:
            if attempt >= len(NETWORK_RETRY_DELAYS) or not never_reached_server(err):
                raise
            logger.info(f"[Notion] Could not reach api.notion.com ({err}); retrying.")
            time.sleep(NETWORK_RETRY_DELAYS[attempt])
    raise RuntimeError("unreachable")


def explain_notion_error(err: Exception) -> tuple[str, bool]:
    """
    Returns (a message for the user, whether the "share the page with your integration" tip applies).
    Only 401/403/404 are access problems. A 400 is a malformed request, and a network failure never
    reached Notion at all, so the sharing tip would mislead in those cases.
    """
    if isinstance(err, error.HTTPError):
        message = ""
        try:
            message = json.loads(err.read().decode("utf-8")).get("message", "")
        except Exception:
            pass
        return message or str(err), err.code in (401, 403, 404)
    if isinstance(err, (error.URLError, OSError)):
        reason = getattr(err, "reason", err)
        return (
            f"Couldn't reach Notion (api.notion.com): {reason}. This is a network problem, not your Notion "
            "setup. Check the internet connection (or allow network access for this tool) and try again.",
            False,
        )
    return str(err), False


def get_notion_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token.strip()}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
        "User-Agent": "Automate-Applications/1.0",
    }


def clean_notion_id(raw_id: str) -> str:
    """Strips hyphens and extracts clean 32-character hex ID from Notion URL or UUID."""
    if not raw_id:
        return ""
    cleaned = raw_id.strip().split("?")[0].split("#")[0].split("/")[-1].replace("-", "")
    if len(cleaned) >= 32:
        cleaned = cleaned[-32:]
    return cleaned


def create_notion_job_database(
    parent_page_id: str,
    title: str = "Automated Job Applications",
    api_token: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """
    Creates a dedicated tabular job database under a given Notion page.
    Configures all columns: Role Title, Company, Location, Source, Apply URL,
    Match Score, Status, and Discovered Date.
    """
    settings = load_settings()
    token = (api_token or settings.notion_api_token).strip()
    if not token:
        raise ValueError("NOTION_API_KEY is not configured.")

    page_id = clean_notion_id(parent_page_id)
    if not page_id:
        raise ValueError("Invalid parent_page_id provided.")

    payload = {
        "parent": {"type": "page_id", "page_id": page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        # Inline: the table renders directly on the parent page. A full-page database only shows
        # there as a one-line link, which new users mistook for "no table was created".
        "is_inline": True,
        "properties": {
            "Role Title": {"title": {}},
            "Company": {
                "select": {}
            },
            "Location": {
                "rich_text": {}
            },
            "Source": {
                "select": {
                    "options": [
                        {"name": "Greenhouse", "color": "green"},
                        {"name": "Lever", "color": "blue"},
                        {"name": "Ashby", "color": "purple"},
                        {"name": "LinkedIn", "color": "blue"},
                        {"name": "Indeed", "color": "orange"},
                        {"name": "Glassdoor", "color": "green"},
                        {"name": "Naukri", "color": "yellow"},
                        {"name": "Google", "color": "pink"},
                        {"name": "Apple", "color": "gray"},
                        {"name": "Netflix", "color": "red"},
                        {"name": "Uber", "color": "default"},
                    ]
                }
            },
            "Apply URL": {"url": {}},
            "Match Score": {"number": {"format": "number"}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "New", "color": "blue"},
                        {"name": "Reviewing", "color": "yellow"},
                        {"name": "Applied", "color": "green"},
                        {"name": "Interview", "color": "purple"},
                        {"name": "Archived", "color": "gray"},
                    ]
                }
            },
            "Discovered Date": {"date": {}},
        },
    }

    req = request.Request(
        f"{NOTION_BASE_URL}/databases",
        data=json.dumps(payload).encode("utf-8"),
        headers=get_notion_headers(token),
        method="POST",
    )

    res_data = _send_json(req, timeout)
    db_id = res_data.get("id")
    db_url = res_data.get("url")
    logger.info(f"Created Notion Database: {title} ({db_id})")
    return {"id": db_id, "url": db_url, "title": title}


def format_job_properties(job: dict[str, Any]) -> dict[str, Any]:
    """Formats job dictionary fields into Notion property schema."""
    title_text = str(job.get("title") or "Unknown Role").strip()[:100]
    company_name = str(job.get("company") or "Unknown").replace(",", "").strip()[:50]
    location_text = str(job.get("location") or "Remote / India").strip()[:100]
    apply_url = str(job.get("url") or "").strip()
    match_score = job.get("match_score")
    status_text = str(job.get("status") or "New").capitalize()

    # Determine pretty source label
    raw_source = str(job.get("source") or "Direct").lower()
    if "greenhouse" in raw_source:
        source_label = "Greenhouse"
    elif "ashby" in raw_source:
        source_label = "Ashby"
    elif "lever" in raw_source:
        source_label = "Lever"
    elif "linkedin" in raw_source:
        source_label = "LinkedIn"
    elif "indeed" in raw_source:
        source_label = "Indeed"
    elif "glassdoor" in raw_source:
        source_label = "Glassdoor"
    elif "naukri" in raw_source:
        source_label = "Naukri"
    elif "netflix" in raw_source:
        source_label = "Netflix"
    elif "google" in raw_source:
        source_label = "Google"
    elif "apple" in raw_source:
        source_label = "Apple"
    elif "uber" in raw_source:
        source_label = "Uber"
    else:
        source_label = raw_source.title()

    props: dict[str, Any] = {
        "Role Title": {
            "title": [{"type": "text", "text": {"content": title_text}}]
        },
        "Company": {
            "select": {"name": company_name or "Company"}
        },
        "Location": {
            "rich_text": [{"type": "text", "text": {"content": location_text}}]
        },
        "Source": {
            "select": {"name": source_label}
        },
        "Status": {
            "select": {"name": status_text}
        },
    }

    if apply_url and apply_url.startswith(("http://", "https://")):
        props["Apply URL"] = {"url": apply_url}

    if match_score is not None and isinstance(match_score, (int, float)):
        props["Match Score"] = {"number": int(match_score)}

    # Date
    disc_at = job.get("discovered_at") or job.get("posted_at")
    if disc_at:
        try:
            # Format ISO date
            date_str = str(disc_at).split("T")[0]
            props["Discovered Date"] = {"date": {"start": date_str}}
        except Exception:
            pass
    else:
        props["Discovered Date"] = {
            "date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        }

    return props


def push_job_to_notion(
    job: dict[str, Any],
    database_id: str,
    api_token: str | None = None,
    timeout: float = 15.0,
) -> str:
    """Creates a page row in the Notion Database. Returns the created page_id."""
    settings = load_settings()
    token = (api_token or settings.notion_api_token).strip()
    if not token:
        raise ValueError("NOTION_API_KEY is missing.")

    db_id = clean_notion_id(database_id)
    if not db_id:
        raise ValueError("Invalid Notion database_id provided.")

    payload = {
        "parent": {"database_id": db_id},
        "properties": format_job_properties(job),
    }

    req = request.Request(
        f"{NOTION_BASE_URL}/pages",
        data=json.dumps(payload).encode("utf-8"),
        headers=get_notion_headers(token),
        method="POST",
    )

    res = _send_json(req, timeout)
    return res.get("id") or ""


def sync_jobs_to_notion(
    database_id: str | None = None,
    api_token: str | None = None,
    limit: int | None = None,
    db_path=DB_PATH,
) -> dict[str, int]:
    """
    Syncs unsynced jobs (where notion_page_id IS NULL) from SQLite into the Notion Database.
    Updates each SQLite record with its notion_page_id to prevent duplicates.
    """
    settings = load_settings()
    token = (api_token or settings.notion_api_token).strip()
    target_db_id = clean_notion_id(database_id or settings.notion_database_id)

    if not token or not target_db_id:
        logger.info("[Notion Sync] NOTION_API_KEY or NOTION_DATABASE_ID missing. Skipping Notion sync.")
        return {"synced": 0, "failed": 0, "skipped": 0}

    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM jobs WHERE notion_page_id IS NULL ORDER BY id DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = conn.execute(query).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"synced": 0, "failed": 0, "skipped": 0}

    from ..scoring import hard_filter_jobs
    raw_dicts = [dict(r) for r in rows]
    valid_jobs = hard_filter_jobs(
        raw_dicts,
        keywords=settings.search_keywords,
        locations=settings.locations,
        exclude=settings.exclude_keywords,
    )
    valid_ids = {j["id"] for j in valid_jobs}

    synced = 0
    failed = 0
    skipped = 0

    for r in rows:
        job_dict = dict(r)
        if job_dict["id"] not in valid_ids:
            # Mark filtered out so it doesn't poll repeatedly
            conn = get_connection(db_path)
            try:
                conn.execute("UPDATE jobs SET notion_page_id = 'skipped_not_target' WHERE id = ?", (r["id"],))
                conn.commit()
            finally:
                conn.close()
            skipped += 1
            continue

        try:
            page_id = push_job_to_notion(job_dict, database_id=target_db_id, api_token=token)
            if page_id:
                conn = get_connection(db_path)
                try:
                    conn.execute("UPDATE jobs SET notion_page_id = ? WHERE id = ?", (page_id, r["id"]))
                    conn.commit()
                finally:
                    conn.close()
                synced += 1
        except Exception as exc:
            logger.warning(f"[Notion Sync] Failed to sync job '{job_dict.get('title')}' ({job_dict.get('url')}): {exc}")
            failed += 1

    return {"synced": synced, "failed": failed, "skipped": skipped}
