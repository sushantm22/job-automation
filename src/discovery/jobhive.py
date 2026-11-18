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

Limitations: Workday (and most SuccessFactors) rows have no posting date, so their freshness comes
from first-seen tracking (see freshness.py). It is a third party's free service; any failure is logged and skipped.
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
COLUMNS = ["title", "company", "location", "url", "posted_at"]
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


# Closed-job tracking safety: if a platform's India row count drops below this fraction of the
# previous snapshot, the snapshot is treated as broken and nothing is closed from it.
MIN_SNAPSHOT_RATIO = 0.5


def _load_cache(path: Path, cache_key: str) -> tuple[dict[str, str], dict[str, int]]:
    """
    Returns (Last-Modified stamps, India row counts) from the previous run. Stamps are only valid
    for the same search settings/database (`cache_key`); counts describe the dataset itself.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}
    stamps = data.get("stamps") if data.get("key") == cache_key else None
    counts = data.get("counts")
    return (stamps if isinstance(stamps, dict) else {}), (counts if isinstance(counts, dict) else {})


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


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
                # Present for Oracle, iCIMS, Darwinbox, Keka; missing for Workday and most SuccessFactors.
                posted_at=_iso(row.get("posted_at")),
            )
        )
    return jobs


def fetch_jobhive_jobs(
    platforms: list[str] | None = None,
    cache_path: Path | None = None,
    opener: Callable[[str], Any] | None = None,
    cache_key: str = "",
    snapshots: dict[str, dict[str, Any]] | None = None,
) -> list[JobRecord]:
    """
    India jobs from the JobHive platform slices. A slice whose Last-Modified matches the cache
    was already processed in an earlier run with the same `cache_key` (search settings), so its
    matches are already in the database and it is skipped.

    If `snapshots` is given, it is filled for every platform read in full this run:
    {platform: {"urls": all India job URLs in the snapshot, "closable": bool}}. "closable" is False
    when the India row count fell below MIN_SNAPSHOT_RATIO of the previous snapshot (likely a broken
    or partial dataset), so closed-job tracking must not use it.
    """
    import pyarrow.parquet as pq

    opener = opener or HTTPRangeFile
    cache, counts = _load_cache(cache_path, cache_key) if cache_path else ({}, {})
    all_jobs: list[JobRecord] = []

    selected = platforms or DEFAULT_PLATFORMS
    for number, platform in enumerate(selected, 1):
        url = f"{BASE_URL}/{platform}/jobs.parquet"
        logger.info(f"[JobHive] {platform} ({number}/{len(selected)})...")
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
            previous = counts.get(platform)
            closable = bool(jobs) and (not previous or len(jobs) >= previous * MIN_SNAPSHOT_RATIO)
            if closable:
                counts[platform] = len(jobs)
            else:
                logger.warning(
                    f"[JobHive] {platform}: snapshot has {len(jobs)} India jobs vs {previous} last time; "
                    "looks incomplete, so no jobs are marked closed from it."
                )
            if snapshots is not None:
                snapshots[platform] = {"urls": {j.url for j in jobs}, "closable": closable}
            mb = getattr(remote, "bytes_read", 0) / 1e6
            logger.info(f"[JobHive] {platform}: {len(jobs)} India jobs of {table.num_rows} ({mb:.1f} MB).")
        except Exception as err:
            logger.warning(f"[JobHive] {platform}: skipped ({err}).")

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"key": cache_key, "stamps": cache, "counts": counts}, indent=2) + "\n", encoding="utf-8"
        )
    return all_jobs
