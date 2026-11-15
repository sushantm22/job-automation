from __future__ import annotations

import json
from typing import Any
from urllib import request

from .base import JobRecord, slug_to_company_name, strip_html


def parse_greenhouse_jobs(payload: dict[str, Any], company_slug: str | None = None) -> list[JobRecord]:
    jobs: list[JobRecord] = []
    records = payload.get("jobs") or []
    # The /jobs endpoint has no board-level name; each job carries `company_name`.
    fallback_company = str(payload.get("name") or slug_to_company_name(company_slug) or "Greenhouse")
    for item in records:
        title = item.get("title") or "Unknown role"
        location = item.get("location") or {}
        if isinstance(location, dict):
            location_name = location.get("name") or ""
        else:
            location_name = str(location)
        url = item.get("absolute_url") or item.get("url") or ""
        description = strip_html(item.get("content") or item.get("description") or "")
        jobs.append(
            JobRecord(
                source="greenhouse",
                company=str(item.get("company_name") or fallback_company).strip(),
                title=str(title),
                location=str(location_name),
                url=str(url),
                description=description,
                posted_at=item.get("updated_at") or item.get("posted_at"),
            )
        )
    return jobs


def fetch_greenhouse_jobs(slug: str) -> list[JobRecord]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    with request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_greenhouse_jobs(payload, company_slug=slug)
