from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import pandas as pd

from .base import JobRecord

logger = logging.getLogger(__name__)


def parse_jobspy_dataframe(df: pd.DataFrame) -> list[JobRecord]:
    """Converts a JobSpy pandas DataFrame into a list of standardized JobRecord objects."""
    records: list[JobRecord] = []
    if df is None or df.empty:
        return records

    for _, row in df.iterrows():
        url = row.get("job_url_direct") or row.get("job_url") or ""
        if not url or pd.isna(url):
            url = str(row.get("job_url") or "")

        location = row.get("location") or ""
        if pd.isna(location):
            location = ""
        is_remote = row.get("is_remote")
        if is_remote is True and "remote" not in str(location).lower():
            location = f"Remote, {location}".strip(", ")

        description = row.get("description") or ""
        if pd.isna(description):
            description = ""

        date_posted = row.get("date_posted")
        posted_at = str(date_posted) if date_posted is not None and not pd.isna(date_posted) else None

        records.append(
            JobRecord(
                source=str(row.get("site") or "jobspy").lower(),
                company=str(row.get("company") or "Unknown Company").strip(),
                title=str(row.get("title") or "Unknown Role").strip(),
                location=str(location).strip(),
                url=str(url).strip(),
                description=str(description).strip(),
                posted_at=posted_at,
            )
        )
    return records


DEFAULT_SITES = ["linkedin", "indeed", "naukri", "glassdoor"]
LINKEDIN_RETRY_WAIT_SECONDS = 60  # LinkedIn's HTTP 429 lifts after about a minute
MAX_CITY_QUERIES = 3  # only used when "India" itself is not one of the locations


def plan_location_queries(locations: list[str] | str | None) -> list[str]:
    """
    Where to search. "India" covers every Indian city on these boards, so searching cities as
    well only repeats results and uses up LinkedIn's rate limit. Cities are searched only when the
    user did not choose India as a whole.
    """
    locs = [locations] if isinstance(locations, str) else [str(l) for l in (locations or [])]
    named = [l.strip() for l in locs if l and l.strip() and l.strip().lower() not in {"remote"}]
    if not named or any(l.lower() == "india" for l in named):
        return ["India"]
    return named[:MAX_CITY_QUERIES]


class _LinkedInThrottleWatch(logging.Handler):
    """Notices JobSpy's "response status code 429" error from its LinkedIn scraper."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.throttled = False

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "429" in message or "blocked" in message.lower():
            self.throttled = True


def _records(df: Any, seen_urls: set[str]) -> list[JobRecord]:
    out = []
    for rec in parse_jobspy_dataframe(df):
        if rec.url and rec.url not in seen_urls:
            seen_urls.add(rec.url)
            out.append(rec)
    return out


def fetch_jobspy_jobs(
    keywords: list[str] | str,
    locations: list[str] | str = "India",
    sites: list[str] | None = None,
    results_wanted: int = 100,
    hours_old: int | None = 720,
    include_remote: bool = True,
    proxies: list[str] | None = None,
    linkedin_hours_old: int | None = None,
    linkedin_pause_seconds: float = 15.0,
    report: dict[str, Any] | None = None,
    scraper: Callable[..., Any] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> list[JobRecord]:
    """
    Searches job boards (LinkedIn, Indeed, Naukri, Glassdoor) for each role, in India.

    - One search per role and location (see plan_location_queries), asking each site for
      `results_wanted` jobs posted in the last `hours_old` hours (None: any time).
    - LinkedIn runs on its own, one search at a time with `linkedin_pause_seconds` between them,
      because it blocks bursts with HTTP 429. When that happens we wait a minute and continue once
      from where it stopped. No proxies or disguises are used. The other sites run in parallel.
    - A remote search runs on Indeed only (LinkedIn and Glassdoor ignore the remote flag, so a
      "remote" search there would just repeat the India search).

    `report`, if given, is filled with {"linkedin": {"complete": bool, "jobs": n},
    "others": {"complete": bool, "jobs": n}} so the caller knows whether a site's search finished.
    """
    if scraper is None:
        try:
            from jobspy import scrape_jobs as scraper
        except ImportError:
            logger.error("python-jobspy is not installed. Run 'pip install python-jobspy'")
            return []

    if isinstance(keywords, str):
        keywords_list = [keywords]
    else:
        keywords_list = [k for k in keywords if k]

    if not keywords_list:
        logger.info("[Tier 2: JobSpy] No job titles are set. Skipping Tier 2.")
        return []

    # Google Jobs is left out: since Jan 2025 Google Search only serves results to clients that run
    # JavaScript, so JobSpy's plain-HTTP Google scraper always returns "no job data returned".
    target_sites = [s for s in (sites or DEFAULT_SITES) if s != "google"]
    other_sites = [s for s in target_sites if s != "linkedin"]
    loc_queries = plan_location_queries(locations)
    li_hours = linkedin_hours_old if linkedin_hours_old is not None else hours_old
    common = {"results_wanted": results_wanted, "country_indeed": "India", "proxies": proxies, "verbose": 0}

    def search_linkedin() -> tuple[list[JobRecord], bool]:
        if "linkedin" not in target_sites:
            return [], True
        seen: set[str] = set()
        found: list[JobRecord] = []
        complete = True
        searches = [(term, loc) for term in keywords_list for loc in loc_queries]
        for number, (term, loc) in enumerate(searches, 1):
            if number > 1 and linkedin_pause_seconds > 0:
                sleep(linkedin_pause_seconds)
            logger.info(f"[Tier 2] LinkedIn: '{term}' in {loc} ({number}/{len(searches)})...")
            got: list[JobRecord] = []
            for attempt in (1, 2):
                watch = _LinkedInThrottleWatch()
                li_logger = logging.getLogger("jobspy.linkedin")
                li_logger.addHandler(watch)
                try:
                    df = scraper(
                        site_name=["linkedin"], search_term=term, location=loc, hours_old=li_hours,
                        offset=len(got), **{**common, "results_wanted": max(1, results_wanted - len(got))},
                    )
                    got += _records(df, seen)
                except Exception as exc:
                    logger.warning("[Tier 2] LinkedIn search failed for '%s': %s", term, exc)
                    complete = False
                    break
                finally:
                    li_logger.removeHandler(watch)
                if not watch.throttled or len(got) >= results_wanted:
                    break
                if attempt == 1:
                    logger.info(
                        f"[Tier 2] LinkedIn rate-limited after {len(got)} results; waiting "
                        f"{LINKEDIN_RETRY_WAIT_SECONDS}s and continuing once..."
                    )
                    sleep(LINKEDIN_RETRY_WAIT_SECONDS)
                else:
                    logger.info(f"[Tier 2] LinkedIn still rate-limited; keeping {len(got)} results for '{term}'.")
                    complete = False
            logger.info(f"[Tier 2] LinkedIn '{term}': {len(got)} jobs.")
            found += got
        return found, complete

    def search_others() -> tuple[list[JobRecord], bool]:
        if not other_sites:
            return [], True
        seen: set[str] = set()
        found: list[JobRecord] = []
        complete = True
        names = "/".join(s.title() for s in other_sites)
        for number, term in enumerate(keywords_list, 1):
            logger.info(f"[Tier 2] {names}: '{term}' ({number}/{len(keywords_list)})...")
            before = len(found)
            for loc in loc_queries:
                try:
                    df = scraper(site_name=other_sites, search_term=term, location=loc, hours_old=hours_old, **common)
                    found += _records(df, seen)
                except Exception as exc:
                    logger.warning("JobSpy scrape failed for keyword '%s' in '%s': %s", term, loc, exc)
                    complete = False
            if include_remote and "indeed" in other_sites:
                try:
                    df = scraper(site_name=["indeed"], search_term=term, location="India", is_remote=True,
                                 hours_old=hours_old, **common)
                    found += _records(df, seen)
                except Exception as exc:
                    logger.warning("JobSpy remote scrape failed for keyword '%s': %s", term, exc)
                    complete = False
            logger.info(f"[Tier 2] {names} '{term}': {len(found) - before} jobs.")
        return found, complete

    with ThreadPoolExecutor(max_workers=2) as pool:
        linkedin_future = pool.submit(search_linkedin)
        others_future = pool.submit(search_others)
        linkedin_jobs, linkedin_complete = linkedin_future.result()
        other_jobs, others_complete = others_future.result()

    if report is not None:
        report["linkedin"] = {"complete": linkedin_complete, "jobs": len(linkedin_jobs)}
        report["others"] = {"complete": others_complete and bool(other_jobs), "jobs": len(other_jobs)}

    seen_urls: set[str] = set()
    all_records: list[JobRecord] = []
    for rec in linkedin_jobs + other_jobs:
        if rec.url not in seen_urls:
            seen_urls.add(rec.url)
            all_records.append(rec)
    return all_records
