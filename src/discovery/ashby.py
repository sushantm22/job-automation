from __future__ import annotations

import json
from typing import Any
from urllib import request

from .base import JobRecord, strip_html


def parse_ashby_jobs(payload: dict[str, Any], company_slug: str = "Ashby") -> list[JobRecord]:
    jobs: list[JobRecord] = []
    records = payload.get("jobs") or []
    for item in records:
        title = item.get("title") or "Unknown role"
        location = item.get("location") or ""
        if item.get("isRemote") is True and "remote" not in str(location).lower():
            location = f"Remote, {location}".strip(", ")

        url = item.get("jobUrl") or item.get("applyUrl") or ""
        description = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml") or "")
        jobs.append(
            JobRecord(
                source="ashby",
                company=company_slug.title(),
                title=str(title),
                location=str(location),
                url=str(url),
                description=str(description),
                posted_at=item.get("publishedAt"),
            )
        )
    return jobs


def fetch_ashby_jobs(slug: str) -> list[JobRecord]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_ashby_jobs(payload, company_slug=slug)
