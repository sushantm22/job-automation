from __future__ import annotations

import logging
from typing import Any
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


def fetch_jobspy_jobs(
    keywords: list[str] | str,
    locations: list[str] | str = "India",
    sites: list[str] | None = None,
    results_wanted: int = 15,
    hours_old: int = 72,
    include_remote: bool = True,
    proxies: list[str] | None = None,
) -> list[JobRecord]:
    """
    Scrapes jobs across job boards (Naukri, LinkedIn, Indeed, Glassdoor) targeting India and Remote.
    
    Args:
        keywords: Search term or list of search terms (e.g. ['Sales Manager', 'Brand Manager'])
        locations: Target location or list of locations (default 'India')
        sites: List of job boards (default ['naukri', 'linkedin', 'indeed', 'glassdoor'])
        results_wanted: Number of results requested per board
        hours_old: Maximum age of postings in hours
        include_remote: Also run a targeted remote search
        proxies: Optional proxy list for high-volume scrapes
    """
    try:
        from jobspy import scrape_jobs
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
    target_sites = sites or ["naukri", "linkedin", "indeed", "glassdoor"]
    all_records: list[JobRecord] = []
    seen_urls: set[str] = set()

    # Determine location queries: always include India and key metro hubs if specified
    if isinstance(locations, str):
        loc_queries = [locations]
    else:
        # Default to pan-India
        loc_queries = ["India"]
        # If user explicitly provided Indian cities, include top ones
        for loc in locations:
            if loc.lower() not in {"remote", "india"} and loc not in loc_queries:
                loc_queries.append(loc)

    for number, term in enumerate(keywords_list, 1):
        logger.info(f"[Tier 2] Searching job sites for '{term}' ({number}/{len(keywords_list)})...")
        # 1. Main location search across India
        for loc in loc_queries[:2]:  # Limit queries to avoid excessive rate limits
            try:
                df = scrape_jobs(
                    site_name=target_sites,
                    search_term=term,
                    location=loc,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    country_indeed="India",
                    proxies=proxies,
                    verbose=0,
                )
                for rec in parse_jobspy_dataframe(df):
                    if rec.url and rec.url not in seen_urls:
                        seen_urls.add(rec.url)
                        all_records.append(rec)
            except Exception as exc:
                logger.warning("JobSpy scrape failed for keyword '%s' in '%s': %s", term, loc, exc)

        # 2. Dedicated Remote search for India
        if include_remote:
            try:
                df_remote = scrape_jobs(
                    site_name=[s for s in target_sites if s != "naukri"],  # Indeed and LinkedIn support is_remote flag
                    search_term=term,
                    location="India",
                    is_remote=True,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    country_indeed="India",
                    proxies=proxies,
                    verbose=0,
                )
                for rec in parse_jobspy_dataframe(df_remote):
                    if rec.url and rec.url not in seen_urls:
                        seen_urls.add(rec.url)
                        all_records.append(rec)
            except Exception as exc:
                logger.warning("JobSpy remote scrape failed for keyword '%s': %s", term, exc)

    return all_records
