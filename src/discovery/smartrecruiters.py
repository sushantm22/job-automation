"""
Tier 1: SmartRecruiters, via its official public Posting API (no key needed).
https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings

Company identifiers are case-sensitive (e.g. "BoschGroup"). Note: the API answers HTTP 200 with
totalFound=0 for identifiers that don't exist, so "no postings" and "no such company" look the same.
"""
from __future__ import annotations

import json
from typing import Any
from urllib import parse, request

from .base import JobRecord, slug_to_company_name

API_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
JOB_URL = "https://jobs.smartrecruiters.com/{company}/{posting_id}"
HEADERS = {"User-Agent": "Automate-Applications/1.0", "Accept": "application/json"}


def _location(loc: dict[str, Any]) -> str:
    # fullLocation looks like "hosur road bangalore, , India"; drop the empty parts.
    full = loc.get("fullLocation") or ", ".join(
        str(loc.get(k) or "") for k in ("city", "region", "country")
    )
    text = ", ".join(part.strip() for part in str(full).split(",") if part.strip())
    if loc.get("remote") and "remote" not in text.lower():
        text = f"Remote, {text}".strip(", ")
    return text


def parse_smartrecruiters_postings(payload: dict[str, Any], company_identifier: str) -> list[JobRecord]:
    jobs: list[JobRecord] = []
    for item in payload.get("content") or []:
        posting_id = item.get("id")
        if not posting_id:
            continue
        company = (item.get("company") or {}).get("name") or slug_to_company_name(company_identifier)
        jobs.append(
            JobRecord(
                source="smartrecruiters",
                company=str(company).strip(),
                title=str(item.get("name") or "Unknown role").strip(),
                location=_location(item.get("location") or {}),
                url=JOB_URL.format(company=company_identifier, posting_id=posting_id),
                description="",  # not in the list response; titles are what the filter matches on
                posted_at=item.get("releasedDate"),
            )
        )
    return jobs


def fetch_smartrecruiters_page(
    company_identifier: str,
    offset: int = 0,
    limit: int = 100,
    country: str | None = "in",
    timeout: float = 20.0,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if country:
        params["country"] = country
    url = API_URL.format(company=parse.quote(company_identifier)) + "?" + parse.urlencode(params)
    with request.urlopen(request.Request(url, headers=HEADERS), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_smartrecruiters_jobs(
    company_identifier: str,
    country: str | None = "in",
    page_size: int = 100,
    max_pages: int = 10,
    timeout: float = 20.0,
) -> list[JobRecord]:
    """
    All postings for one company, filtered server-side to a country (default India, matching this
    project's India + Remote focus). Pages through results up to max_pages * page_size postings.
    """
    jobs: list[JobRecord] = []
    for page in range(max_pages):
        payload = fetch_smartrecruiters_page(
            company_identifier, offset=page * page_size, limit=page_size, country=country, timeout=timeout
        )
        batch = parse_smartrecruiters_postings(payload, company_identifier)
        jobs.extend(batch)
        if not batch or (page + 1) * page_size >= int(payload.get("totalFound") or 0):
            break
    return jobs
