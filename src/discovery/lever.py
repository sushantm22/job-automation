from __future__ import annotations

import json
from typing import Any
from urllib import request

from .base import JobRecord, slug_to_company_name, strip_html


def parse_lever_jobs(payload: list[dict[str, Any]], company_slug: str | None = None) -> list[JobRecord]:
    jobs: list[JobRecord] = []
    # Lever postings carry no company field; the board slug is the only reliable identifier.
    fallback_company = slug_to_company_name(company_slug) or "Lever"
    for item in payload:
        title = item.get("text") or item.get("title") or "Unknown role"
        categories = item.get("categories") or {}
        location = categories.get("location") or item.get("location") or ""
        description = strip_html(item.get("description") or item.get("descriptionHtml") or "")
        url = item.get("hostedUrl") or item.get("url") or ""
        jobs.append(
            JobRecord(
                source="lever",
                company=str(item.get("company") or fallback_company).strip(),
                title=str(title),
                location=str(location),
                url=str(url),
                description=description,
                posted_at=item.get("createdAt") or item.get("postedAt"),
            )
        )
    return jobs


def fetch_lever_jobs(slug: str) -> list[JobRecord]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    with request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_lever_jobs(payload, company_slug=slug)
