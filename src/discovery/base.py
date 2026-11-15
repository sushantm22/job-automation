from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def get_text(self) -> str:
        return " ".join(self.parts)


def strip_html(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, dict):
        value = value.get("text") or value.get("html") or value.get("content") or value.get("description") or str(value)
    elif not isinstance(value, str):
        value = str(value)
    parser = _HTMLStripper()
    parser.feed(value)
    parser.close()
    return re.sub(r"\s+", " ", parser.get_text()).strip()


@dataclass
class JobRecord:
    source: str
    company: str
    title: str
    location: str
    url: str
    description: str
    posted_at: str | None = None

    @classmethod
    def from_mapping(cls, data: dict, source: str) -> "JobRecord":
        location = data.get("location") or ""
        if isinstance(location, dict):
            location = location.get("name") or ""
        title = data.get("title") or data.get("text") or "Unknown role"
        description = strip_html(data.get("description") or data.get("content") or data.get("descriptionHtml") or "")
        url = data.get("url") or data.get("absolute_url") or data.get("hostedUrl") or ""
        company = data.get("company") or data.get("organization") or source.title()
        return cls(
            source=source,
            company=company,
            title=title,
            location=str(location),
            url=url,
            description=description,
            posted_at=data.get("posted_at") or data.get("createdAt") or data.get("updated_at"),
        )


def slug_to_company_name(slug: str | None) -> str:
    """Turns an ATS board slug like 'apollo-graphql' into a display name ('Apollo Graphql')."""
    return re.sub(r"[-_]+", " ", (slug or "").strip()).title()


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def hard_filter_jobs(jobs: Iterable[dict], keywords: list[str], locations: list[str], exclude: list[str]) -> list[dict]:
    keyword_tokens = [normalize_text(item) for item in keywords if item]
    exclude_tokens = [normalize_text(item) for item in exclude if item]
    location_tokens = [normalize_text(item) for item in locations if item]

    matches: list[dict] = []
    for job in jobs:
        text_block = " ".join(
            [
                str(job.get("title") or ""),
                str(job.get("location") or ""),
                str(job.get("description") or ""),
            ]
        )
        normalized = normalize_text(text_block)

        excludes_hit = any(token in normalized for token in exclude_tokens)
        if excludes_hit:
            continue

        if keyword_tokens and not any(token in normalized for token in keyword_tokens):
            continue

        if location_tokens and not any(token in normalize_text(str(job.get("location") or "")) for token in location_tokens):
            continue

        matches.append(job)
    return matches
