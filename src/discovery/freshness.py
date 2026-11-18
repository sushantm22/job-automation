"""
Job freshness: posting-date parsing and the rules for keeping job lists recent.

- Jobs with a known posting date older than `max_job_age_days` are dropped at discovery and,
  once stored, closed as they age past it.
- Jobs without a posting date from bulk sources (the JobHive dataset, live SuccessFactors) use
  "first seen" tracking: the first read of a source/company is recorded as a baseline and not
  added; afterwards only listings that newly appear are added, so they are at most a run old.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def parse_posted_at(value: Any) -> datetime | None:
    """Accepts ISO strings, dates, datetimes and epoch seconds/milliseconds (Lever). UTC-aware."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime(value.year, value.month, value.day)
        elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            number = float(value)
            dt = datetime.fromtimestamp(number / 1000 if number > 1e11 else number, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_in_days(value: Any, now: datetime | None = None) -> float | None:
    dt = parse_posted_at(value)
    if dt is None:
        return None
    return ((now or datetime.now(timezone.utc)) - dt).total_seconds() / 86400


def is_too_old(value: Any, max_days: int, now: datetime | None = None) -> bool:
    """True only for a known posting date older than max_days (unknown dates are never 'too old')."""
    if not max_days or max_days <= 0:
        return False
    age = age_in_days(value, now)
    return age is not None and age > max_days


def uses_first_seen(source: str) -> bool:
    """Sources whose listings mostly lack posting dates and arrive as a big backlog."""
    return source.startswith("jobhive:") or source == "successfactors"


def first_seen_scope(source: str, company: str) -> str:
    """Baseline unit: a whole dataset platform, or one company for live scrapers."""
    return source if source.startswith("jobhive:") else f"{source}|{(company or '').strip().lower()}"
