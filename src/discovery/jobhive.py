"""
Tier 1 (dataset): JobHive, a free public dataset of live jobs collected from company ATS career
sites (https://storage.stapply.ai/jobhive/v1/manifest.json, published by the MIT-licensed
`ats-scrapers` project).

It covers platforms we cannot query directly, notably Workday (whose job endpoint blocks
non-browser clients), Oracle, SuccessFactors, iCIMS and the Indian HR systems Darwinbox and Keka.

We only read the published Parquet files; we do not run the `ats-scrapers` package. Parquet is
columnar, so HTTP Range requests fetch just the columns we need (title, company, location, url):
~50 MB for all six platforms instead of ~850 MB, and nothing at all when a file hasn't changed
since the last run (the dataset is regenerated about once a day).

Limitations: the dataset has no posting dates, so a job's presence only means it was live in the
latest snapshot. It is a third party's free service; any failure is logged and skipped.
"""
from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable
from urllib import request

from .base import JobRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://storage.stapply.ai/jobhive/v1"
DEFAULT_PLATFORMS = ["workday", "oracle", "successfactors", "icims", "darwinbox", "keka"]
COLUMNS = ["title", "company", "location", "url"]
# Honest identification. The storage CDN rejects Python's default "Python-urllib" agent.
HEADERS = {"User-Agent": "Automate-Applications/1.0 (job-discovery; JobHive dataset reader)"}

# Full place names only. Two-letter state codes (KA, TN, ...) collide with US states in this
# mostly-US dataset ("Memphis, TN"), so they are deliberately not used for this pre-filter.
INDIA_PLACES = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|secunderabad|pune|mumbai|navi mumbai|thane|gurgaon|"
    r"gurugram|noida|greater noida|delhi|new delhi|faridabad|ghaziabad|chennai|kolkata|ahmedabad|"
    r"vadodara|surat|coimbatore|kochi|cochin|thiruvananthapuram|trivandrum|jaipur|lucknow|indore|"
    r"bhopal|nagpur|visakhapatnam|vijayawada|mysuru|mysore|mangalore|mangaluru|chandigarh|mohali|"
    r"bhubaneswar|guwahati|patna|ranchi|raipur|dehradun|goa|karnataka|maharashtra|telangana|"
    r"tamil nadu|kerala|gujarat|haryana|punjab|rajasthan|uttar pradesh|west bengal|andhra pradesh|"
    r"madhya pradesh|odisha)\b",
    re.IGNORECASE,
)


class HTTPRangeFile(io.RawIOBase):
    """Read-only, seekable file over HTTP Range requests, so pyarrow can read single columns."""

    def __init__(self, url: str, timeout: float = 60.0) -> None:
        self.url, self.timeout, self.pos, self.bytes_read = url, timeout, 0, 0
        with request.urlopen(request.Request(url, method="HEAD", headers=HEADERS), timeout=timeout) as resp:
            self.size = int(resp.headers["Content-Length"])
            self.last_modified = resp.headers.get("Last-Modified") or ""

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else (self.pos + offset if whence == 1 else self.size + offset)
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        req = request.Request(self.url, headers={**HEADERS, "Range": f"bytes={self.pos}-{end}"})
        with request.urlopen(req, timeout=self.timeout) as resp:
            data = resp.read()
        self.pos += len(data)
        self.bytes_read += len(data)
        return data

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def _load_stamps(path: Path, cache_key: str) -> dict[str, str]:
    """Last-Modified stamps from the previous run, or {} if the search settings/database changed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("key") != cache_key:
        return {}
    stamps = data.get("stamps")
    return stamps if isinstance(stamps, dict) else {}


def rows_to_jobs(rows: list[dict[str, Any]], platform: str) -> list[JobRecord]:
    """Keeps rows located in India and converts them to JobRecords."""
    jobs: list[JobRecord] = []
    for row in rows:
        location = str(row.get("location") or "").strip()
        url = str(row.get("url") or "").strip()
        if not url or not INDIA_PLACES.search(location):
            continue
        jobs.append(
            JobRecord(
                source=f"jobhive:{platform}",
                company=str(row.get("company") or "Unknown Company").strip(),
                title=str(row.get("title") or "Unknown Role").strip(),
                location=location,
                url=url,
                description="",
                posted_at=None,  # not available in the dataset
            )
        )
    return jobs


def fetch_jobhive_jobs(
    platforms: list[str] | None = None,
    cache_path: Path | None = None,
    opener: Callable[[str], Any] | None = None,
    cache_key: str = "",
) -> list[JobRecord]:
    """
    India jobs from the JobHive platform slices. A slice whose Last-Modified matches the cache
    was already processed in an earlier run with the same `cache_key` (search settings), so its
    matches are already in the database and it is skipped.
    """
    import pyarrow.parquet as pq

    opener = opener or HTTPRangeFile
    cache = _load_stamps(cache_path, cache_key) if cache_path else {}
    all_jobs: list[JobRecord] = []

    for platform in platforms or DEFAULT_PLATFORMS:
        url = f"{BASE_URL}/{platform}/jobs.parquet"
        try:
            remote = opener(url)
            stamp = getattr(remote, "last_modified", "")
            if stamp and cache.get(platform) == stamp:
                logger.info(f"[JobHive] {platform}: unchanged since last run ({stamp}); skipped.")
                continue
            table = pq.ParquetFile(remote).read(columns=COLUMNS)
            jobs = rows_to_jobs(table.to_pylist(), platform)
            all_jobs.extend(jobs)
            if stamp:
                cache[platform] = stamp
            mb = getattr(remote, "bytes_read", 0) / 1e6
            logger.info(f"[JobHive] {platform}: {len(jobs)} India jobs of {table.num_rows} ({mb:.1f} MB).")
        except Exception as err:
            logger.warning(f"[JobHive] {platform}: skipped ({err}).")

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"key": cache_key, "stamps": cache}, indent=2) + "\n", encoding="utf-8")
    return all_jobs
