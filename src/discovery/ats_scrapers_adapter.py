"""
Tier 1 (live): Keka and SuccessFactors career sites, scraped live with the open-source
`ats-scrapers` package (https://github.com/kalil0321/ats-scrapers, MIT).

Only the package's core install is used. Its `[scrapers]`/`[all]` extras add browser-impersonation
tooling (httpcloak, cloakbrowser) for getting past bot protection; we never install those, and
`_scraper_class` refuses any scraper configured to use them, so a scraper that would need them is
skipped instead.

Workday is not scraped live: its job endpoint blocks plain clients. Workday comes from the daily
JobHive dataset instead (see jobhive.py), with closed-job tracking.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .base import JobRecord

logger = logging.getLogger(__name__)

# Registry platform name -> ats-scrapers ATS name. Slugs: Keka = portal URL
# (https://{company}.keka.com/careers); SuccessFactors = careers host (careers.wipro.com).
LIVE_PLATFORMS = {"keka": "keka", "successfactors": "successfactors"}

_INDIA_WORDS = re.compile(r"\bindia\b", re.IGNORECASE)


def _scraper_class(platform: str) -> Any:
    from ats_scrapers.scrapers import ScraperRegistry

    cls = ScraperRegistry.get(LIVE_PLATFORMS[platform])
    # Plain HTTP only: never a scraper that uses or escalates to TLS/browser impersonation.
    if getattr(cls, "fetch_engine", "httpx") != "httpx" or getattr(cls, "fetch_escalate", False):
        raise ValueError(f"{cls.__name__} requires browser impersonation; not used by this project.")
    return cls


def job_to_record(job: Any, platform: str) -> JobRecord:
    location = (job.location or "").strip()
    # Some SuccessFactors sites give only a country code ("IN"); make India explicit for the filter.
    if (job.country_iso or "").upper() == "IN" and not _INDIA_WORDS.search(location):
        location = f"{location}, India".strip(", ") if location.upper() not in {"IN", "IND"} else "India"
    if job.is_remote and "remote" not in location.lower():
        location = f"Remote, {location}".strip(", ")
    return JobRecord(
        source=platform,
        company=(job.company or "Unknown Company").strip(),
        title=(job.title or "Unknown Role").strip(),
        location=location,
        url=str(job.url),
        description=(job.description or "")[:4000],
        posted_at=job.posted_at.isoformat() if job.posted_at else None,
    )


def fetch_live_ats_jobs(platform: str, slug: str, timeout: float = 60.0) -> list[JobRecord]:
    """All current postings for one company, live from its career site."""
    cls = _scraper_class(platform)
    scraper = cls(slug, timeout=timeout, include_descriptions=False)
    return [job_to_record(job, platform) for job in scraper.fetch()]
