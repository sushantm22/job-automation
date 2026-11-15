from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib import request

import yaml

from .base import JobRecord, strip_html

logger = logging.getLogger(__name__)

COMPANIES_YAML_PATH = Path(__file__).resolve().parent / "companies.yaml"


def load_enterprise_portals(yaml_path: Path = COMPANIES_YAML_PATH) -> list[dict[str, str]]:
    """Loads the enterprise_portals list from companies.yaml dynamically."""
    if not yaml_path.exists():
        return []
    try:
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        portals = data.get("enterprise_portals", [])
        if isinstance(portals, list):
            return [p for p in portals if isinstance(p, dict) and p.get("url")]
        return []
    except Exception:
        return []

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "url"],
            },
        }
    },
    "required": ["jobs"],
}


def parse_firecrawl_extracted_jobs(
    data: dict[str, Any],
    default_company: str = "Enterprise Portal",
    base_url: str = "",
) -> list[JobRecord]:
    """
    Parses structured JSON extraction returned by Firecrawl or extracts
    job links from scraped markdown.
    """
    records: list[JobRecord] = []
    extract_data = data.get("extract") or {}
    jobs_list = extract_data.get("jobs") or []

    # 1. Structured JSON extraction succeeded
    if isinstance(jobs_list, list) and jobs_list:
        for item in jobs_list:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Engineering Role").strip()
            url = str(item.get("url") or "").strip()
            if not url or len(title) < 2:
                continue

            # Ensure absolute URL
            if url.startswith("/"):
                from urllib.parse import urljoin
                url = urljoin(base_url, url)

            company = str(item.get("company") or default_company).strip()
            location = str(item.get("location") or "India / Remote").strip()
            description = strip_html(str(item.get("description") or ""))

            records.append(
                JobRecord(
                    source=f"firecrawl:{default_company.lower()}",
                    company=company,
                    title=title,
                    location=location,
                    url=url,
                    description=description,
                )
            )
        if records:
            return records

    # 2. Fallback: Parse markdown links if structured extraction was empty
    markdown = data.get("markdown") or ""
    if markdown:
        # Match markdown links: [Title](https://...)
        link_matches = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", markdown)
        for link_text, link_url in link_matches:
            clean_title = link_text.strip()
            # Filter out non-job navigation links
            if any(
                term in clean_title.lower()
                for term in ["engineer", "developer", "lead", "architect", "analyst", "specialist", "manager", "qa", "sdet"]
            ):
                records.append(
                    JobRecord(
                        source=f"firecrawl:{default_company.lower()}",
                        company=default_company,
                        title=clean_title,
                        location="India / Remote",
                        url=link_url.strip(),
                        description=f"Extracted from {default_company} career portal.",
                    )
                )

    return records


def scrape_portal_with_firecrawl(
    portal_url: str,
    company_name: str,
    api_key: str,
    timeout: float = 25.0,
) -> list[JobRecord]:
    """
    Scrapes a single enterprise portal using Firecrawl's scrape & extract endpoint.
    Handles client-side SPA hydration and anti-scraping blocks automatically.
    """
    endpoint = "https://api.firecrawl.dev/v1/scrape"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "Automate-Applications/1.0",
    }

    payload = {
        "url": portal_url,
        "formats": ["extract", "markdown"],
        "extract": {
            "prompt": (
                f"Extract all open technology, engineering, developer, and data job listings "
                f"for {company_name} in India or Remote, including title, location, direct application url, and description."
            ),
            "schema": EXTRACTION_SCHEMA,
        },
    }

    try:
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=timeout) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("success") and "data" in res_data:
                jobs = parse_firecrawl_extracted_jobs(
                    res_data["data"],
                    default_company=company_name,
                    base_url=portal_url,
                )
                logger.info(
                    f"[Tier 4: Firecrawl] Extracted {len(jobs)} postings from {company_name} ({portal_url})"
                )
                return jobs
            logger.warning(f"[Tier 4: Firecrawl] Unsuccessful response for {company_name}: {res_data}")
            return []

    except request.HTTPError as err:
        if err.code == 401:
            logger.warning("[Tier 4: Firecrawl] Invalid FIRECRAWL_API_KEY. Skipping Tier 4.")
        elif err.code == 402:
            logger.warning("[Tier 4: Firecrawl] Insufficient Firecrawl credits. Skipping Tier 4.")
        else:
            logger.warning(f"[Tier 4: Firecrawl] HTTP error {err.code} for {company_name}: {err.reason}")
        return []
    except Exception as exc:
        logger.warning(f"[Tier 4: Firecrawl] Error scraping {company_name}: {exc}")
        return []


def fetch_firecrawl_portal_jobs(
    portals: list[dict[str, str]] | None = None,
    api_key: str | None = None,
    timeout: float = 25.0,
    budget: int = 10,
    covered_companies: set[str] | None = None,
) -> list[JobRecord]:
    """
    Executes Tier 4 enterprise portal scraping as a smart fallback.

    Only scrapes portals for companies NOT already covered by Tiers 1-2.
    Respects a per-run credit budget to conserve free-tier Firecrawl credits.

    Args:
        portals: List of portal dicts with 'name' and 'url'. Defaults to companies.yaml.
        api_key: Firecrawl API key. Skips gracefully if empty.
        timeout: HTTP timeout per portal.
        budget: Maximum number of portals to scrape per run (1 credit each).
        covered_companies: Set of lowercase company names already found in Tiers 1-2.
    """
    key = (api_key or "").strip()
    if not key:
        logger.info(
            "[Tier 4: Firecrawl] No FIRECRAWL_API_KEY provided. Skipping Tier 4 (Enterprise portals scraping)."
        )
        return []

    target_portals = portals if portals else load_enterprise_portals()
    covered = {c.lower() for c in (covered_companies or set())}
    all_records: list[JobRecord] = []
    credits_used = 0

    for item in target_portals:
        if credits_used >= budget:
            logger.info(
                f"[Tier 4: Firecrawl] Credit budget exhausted ({budget} portals). "
                f"Remaining portals skipped to conserve free-tier credits."
            )
            break

        company_name = item.get("name") or "Enterprise"
        portal_url = item.get("url") or ""
        if not portal_url:
            continue

        # Smart fallback: skip companies already covered by Tiers 1-2
        if company_name.lower() in covered:
            logger.info(f"[Tier 4: Firecrawl] Skipping {company_name} — already covered by Tiers 1-2.")
            continue

        portal_jobs = scrape_portal_with_firecrawl(
            portal_url=portal_url,
            company_name=company_name,
            api_key=key,
            timeout=timeout,
        )
        credits_used += 1
        all_records.extend(portal_jobs)

    logger.info(
        f"[Tier 4: Firecrawl] Used {credits_used}/{budget} credits, "
        f"extracted {len(all_records)} total jobs from {credits_used} portals."
    )
    return all_records
