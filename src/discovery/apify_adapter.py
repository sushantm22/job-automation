from __future__ import annotations

import json
import logging
from typing import Any
from urllib import parse, request

from .base import JobRecord, strip_html

logger = logging.getLogger(__name__)


def parse_apify_naukri_items(items: list[dict[str, Any]]) -> list[JobRecord]:
    """
    Normalizes dataset records returned by Apify Naukri crawlers into standard JobRecord models.
    Tolerates diverse schema variants across different Apify actor implementations.
    """
    records: list[JobRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        raw_title = (
            item.get("title")
            or item.get("jobTitle")
            or item.get("role")
            or item.get("designation")
            or "Unknown Role"
        )
        title = raw_title.get("name") if isinstance(raw_title, dict) else str(raw_title).strip()

        raw_company = (
            item.get("companyName")
            or item.get("company")
            or item.get("hiringOrganization")
            or "Naukri Employer"
        )
        if isinstance(raw_company, dict):
            company = str(raw_company.get("name") or raw_company.get("label") or "Naukri Employer").strip()
        else:
            company = str(raw_company).strip()

        location_raw = (
            item.get("location")
            or item.get("jobLocation")
            or item.get("city")
            or item.get("locations")
            or "India"
        )
        if isinstance(location_raw, list):
            location_parts = []
            for loc in location_raw:
                if isinstance(loc, dict):
                    name = loc.get("label") or loc.get("name") or loc.get("city") or ""
                    if name:
                        location_parts.append(str(name))
                elif loc:
                    location_parts.append(str(loc))
            location = ", ".join(location_parts) if location_parts else "India"
        elif isinstance(location_raw, dict):
            location = str(location_raw.get("label") or location_raw.get("name") or location_raw.get("city") or "India")
        else:
            location = str(location_raw).strip() or "India"

        url = (
            item.get("url")
            or item.get("jobUrl")
            or item.get("link")
            or item.get("applyUrl")
            or ""
        ).strip()

        description = strip_html(
            item.get("description")
            or item.get("jobDescription")
            or item.get("snippet")
            or item.get("job_description")
            or ""
        )

        posted_at = (
            item.get("posted_at")
            or item.get("postedDate")
            or item.get("created_at")
            or item.get("date")
        )

        if not url and not title:
            continue

        records.append(
            JobRecord(
                source="apify:naukri",
                company=company,
                title=title,
                location=location,
                url=url,
                description=description,
                posted_at=str(posted_at) if posted_at else None,
            )
        )

    return records


def fetch_apify_naukri_jobs(
    keywords: list[str],
    locations: list[str],
    api_token: str | None = None,
    actor_id: str = "apify/naukri-scraper",
    max_jobs: int = 30,
    timeout: float = 60.0,
) -> list[JobRecord]:
    """
    Runs an Apify cloud actor to scrape Naukri with anti-bot, residential IP proxy,
    and CAPTCHA solving. Runs synchronously and returns normalized JobRecord objects.

    Guarantees ZERO human intervention:
    - If api_token is missing, gracefully returns [] with an informational message.
    - If network, timeout, or rate-limits occur, logs and returns [] without stopping the pipeline.
    """
    token = (api_token or "").strip()
    if not token:
        logger.info(
            "[Tier 3: Apify] No APIFY_API_TOKEN provided. Skipping Tier 3 (Naukri cloud anti-bot scraping)."
        )
        return []

    # Encode actor slug properly (e.g. apify/naukri-scraper -> apify~naukri-scraper)
    safe_actor_id = actor_id.replace("/", "~")
    api_url = (
        f"https://api.apify.com/v2/acts/{safe_actor_id}/run-sync-get-dataset-items"
        f"?token={parse.quote(token)}&timeout={int(timeout)}"
    )

    if not keywords:
        logger.info("[Tier 3: Apify] No job titles are set. Skipping Tier 3.")
        return []
    query_str = keywords[0]
    loc_str = locations[0] if locations else "India"
    keywords_str = ", ".join(keywords[:3])

    actor_input = {
        "keyword": query_str,
        "keywords": keywords_str,
        "query": query_str,
        "search": query_str,
        "location": loc_str,
        "maxJobs": max_jobs,
        "maxItems": max_jobs,
        "resultsLimit": max_jobs,
        "limit": max_jobs,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Automate-Applications/1.0",
    }

    try:
        req = request.Request(
            api_url,
            data=json.dumps(actor_input).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                jobs = parse_apify_naukri_items(data)
                logger.info(f"[Tier 3: Apify] Successfully fetched {len(jobs)} jobs via {actor_id}")
                return jobs
            logger.warning(f"[Tier 3: Apify] Unexpected response shape from actor: {type(data)}")
            return []

    except request.HTTPError as err:
        if err.code == 401:
            logger.warning("[Tier 3: Apify] Invalid APIFY_API_TOKEN. Skipping Tier 3.")
        elif err.code == 402:
            logger.warning("[Tier 3: Apify] Insufficient Apify account credits. Skipping Tier 3.")
        elif err.code == 404:
            logger.warning(f"[Tier 3: Apify] Actor '{actor_id}' not found on Apify. Skipping Tier 3.")
        else:
            logger.warning(f"[Tier 3: Apify] HTTP error {err.code}: {err.reason}")
        return []
    except Exception as exc:
        logger.warning(f"[Tier 3: Apify] Failed to fetch jobs via Apify: {exc}")
        return []
