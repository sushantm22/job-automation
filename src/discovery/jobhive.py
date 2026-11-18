"""
Tier 1 (dataset): JobHive, a free public dataset of live jobs collected from company ATS career
sites (https://storage.stapply.ai/jobs/v1/manifest.json, published by the MIT-licensed
`ats-scrapers` project). The older `jobhive/v1` location is deprecated; file URLs are taken from
the manifest, which also says where the dataset moved if it moves again.

It covers platforms we cannot query directly, notably Workday (whose job endpoint blocks
non-browser clients), Oracle, SuccessFactors, iCIMS, Phenom and the Indian HR systems Darwinbox,
Keka and Zoho Recruit, plus company-wide Greenhouse/Lever/Ashby/SmartRecruiters coverage.

We only read the published Parquet files; we do not run the `ats-scrapers` package. Parquet is
columnar, so HTTP Range requests fetch just the columns we need (title, company, location, url,
posted_at, country_iso) instead of whole files, and nothing at all when a file hasn't changed since
the last run (the dataset is regenerated about once a day).

Limitations: Workday (and most SuccessFactors) rows have no posting date, so their freshness comes
from first-seen tracking (see freshness.py). It is a third party's free service: temporary server
errors are retried, and any other failure is logged and that source skipped for this run.
"""
from __future__ import annotations

import http.client
import io
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib import request
from urllib.error import HTTPError, URLError

from .base import JobRecord

logger = logging.getLogger(__name__)

MANIFEST_URL = "https://storage.stapply.ai/jobs/v1/manifest.json"
BASE_URL = "https://storage.stapply.ai/jobs/v1"  # fallback when the manifest can't be read
# Kept in sync with DEFAULT_JOBHIVE_PLATFORMS in src/config.py (a test checks it).
DEFAULT_PLATFORMS = [
    "workday", "oracle", "successfactors", "icims", "darwinbox", "keka",
    "smartrecruiters", "phenom", "greenhouse", "lever", "ashby", "workable", "zoho_recruit",
    "amazon", "eightfold", "jibe",
]
# Only these columns are downloaded (and only those a file actually has).
COLUMNS = ["title", "company", "location", "url", "posted_at", "country_iso"]
# Honest identification. The storage CDN rejects Python's default "Python-urllib" agent.
HEADERS = {"User-Agent": "Automate-Applications/1.0 (job-discovery; JobHive dataset reader)"}
# Waits before retrying a temporary server error (HTTP 5xx, timeout, dropped connection).
RETRY_DELAYS = (5, 15)
READ_WORKERS = 4  # sources downloaded in parallel

# Full place names only. Two-letter state codes (KA, TN, ...) collide with US states in this
# mostly-US dataset ("Memphis, TN"), so they are deliberately not used for this pre-filter.
# Rows with country_iso == "IN" are kept even when the location text has no place name.
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


def load_manifest(url: str = MANIFEST_URL, timeout: float = 30.0, _hops: int = 0) -> dict[str, Any]:
    """The dataset manifest. Follows `deprecated_prefixes` if the dataset has moved again."""
    with request.urlopen(request.Request(url, headers=HEADERS), timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        return {}
    prefix = url.split("storage.stapply.ai/", 1)[-1].rsplit("/manifest.json", 1)[0]
    moved = (data.get("deprecated_prefixes") or {}).get(prefix) or {}
    if moved.get("manifest") and moved["manifest"] != url and _hops < 3:
        logger.info(f"[JobHive] Dataset moved from {prefix} to {moved.get('replaced_by')}; following it.")
        return load_manifest(moved["manifest"], timeout, _hops + 1)
    return data


def platform_urls(platforms: list[str], manifest: dict[str, Any] | None) -> dict[str, str]:
    """Parquet URL per source: from the manifest when listed there, else the canonical pattern."""
    by_ats = (manifest or {}).get("by_ats") or {}
    urls: dict[str, str] = {}
    for platform in platforms:
        entry = by_ats.get(platform) if isinstance(by_ats, dict) else None
        url = entry.get("parquet") if isinstance(entry, dict) else None
        urls[platform] = url or f"{BASE_URL}/{platform}/jobs.parquet"
    return urls


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


def _is_india(row: dict[str, Any]) -> bool:
    return str(row.get("country_iso") or "").strip().upper() == "IN" or bool(
        INDIA_PLACES.search(str(row.get("location") or ""))
    )


def rows_to_jobs(rows: list[dict[str, Any]], platform: str) -> list[JobRecord]:
    """Keeps rows located in India (country code IN, or an Indian place name) as JobRecords."""
    jobs: list[JobRecord] = []
    for row in rows:
        location = str(row.get("location") or "").strip()
        url = str(row.get("url") or "").strip()
        if not url or not _is_india(row):
            continue
        jobs.append(
            JobRecord(
                source=f"jobhive:{platform}",
                company=str(row.get("company") or "Unknown Company").strip(),
                title=str(row.get("title") or "Unknown Role").strip(),
                location=location or "India",
                url=url,
                description="",
                # Present for most sources; missing for Workday and most SuccessFactors.
                posted_at=_iso(row.get("posted_at")),
            )
        )
    return jobs


def _india_rows(table: Any) -> list[dict[str, Any]]:
    """
    India rows of a pyarrow table as dicts. Filtering happens inside pyarrow first, so only a few
    thousand rows (not hundreds of thousands) become Python objects.
    """
    try:
        import pyarrow as pa
        import pyarrow.compute as pc

        mask = None
        for name in ("country_iso", "location"):
            if name not in table.column_names:
                continue
            column = table[name]
            if pa.types.is_null(column.type):
                continue
            text = pc.fill_null(pc.cast(column, pa.string()), "")
            if name == "country_iso":
                hit = pc.equal(pc.utf8_upper(pc.utf8_trim_whitespace(text)), "IN")
            else:
                hit = pc.match_substring_regex(text, INDIA_PLACES.pattern, ignore_case=True)
            mask = hit if mask is None else pc.or_(mask, hit)
        if mask is None:
            return []
        return table.filter(mask).to_pylist()
    except Exception as err:  # unexpected column types: fall back to filtering in Python
        logger.debug(f"[JobHive] pyarrow filter failed ({err}); filtering rows in Python.")
        return [row for row in table.to_pylist() if _is_india(row)]


def _is_transient(err: BaseException) -> bool:
    """Server-side or network hiccups worth retrying (never 'no internet' or a missing file)."""
    if isinstance(err, HTTPError):
        return err.code >= 500 or err.code == 429
    if isinstance(err, (TimeoutError, ConnectionError, http.client.IncompleteRead, http.client.RemoteDisconnected)):
        return True
    if isinstance(err, URLError):
        return isinstance(err.reason, (TimeoutError, ConnectionError))
    return False


def _read_platform(
    url: str, opener: Callable[[str], Any], cached_stamp: str | None, sleep: Callable[[float], Any]
) -> dict[str, Any]:
    """Downloads one source's columns (retrying temporary errors) and returns its India rows."""
    import pyarrow.parquet as pq

    attempt = 0
    while True:
        try:
            remote = opener(url)
            stamp = getattr(remote, "last_modified", "")
            if stamp and cached_stamp == stamp:
                return {"unchanged": True, "stamp": stamp}
            parquet = pq.ParquetFile(remote)
            names = set(parquet.schema_arrow.names)
            table = parquet.read(columns=[c for c in COLUMNS if c in names])
            return {
                "unchanged": False,
                "stamp": stamp,
                "rows": _india_rows(table),
                "num_rows": table.num_rows,
                "bytes": getattr(remote, "bytes_read", 0),
            }
        except Exception as err:
            if attempt < len(RETRY_DELAYS) and _is_transient(err):
                delay = RETRY_DELAYS[attempt]
                attempt += 1
                logger.info(f"[JobHive] temporary error reading {url.rsplit('/', 2)[-2]} ({err}); retrying in {delay}s...")
                sleep(delay)
                continue
            raise


def fetch_jobhive_jobs(
    platforms: list[str] | None = None,
    cache_path: Path | None = None,
    opener: Callable[[str], Any] | None = None,
    cache_key: str = "",
    snapshots: dict[str, dict[str, Any]] | None = None,
    manifest: dict[str, Any] | None = None,
    workers: int = READ_WORKERS,
    sleep: Callable[[float], Any] = time.sleep,
) -> list[JobRecord]:
    """
    India jobs from the JobHive source files. A file whose Last-Modified matches the cache was
    already processed in an earlier run with the same `cache_key` (search settings), so its
    matches are already in the database and it is skipped.

    If `snapshots` is given, it is filled for every source read in full this run:
    {platform: {"urls": all India job URLs in the snapshot, "closable": bool}}. "closable" is False
    when the India row count fell below MIN_SNAPSHOT_RATIO of the previous snapshot (likely a broken
    or partial dataset), so closed-job tracking must not use it.
    """
    opener = opener or HTTPRangeFile
    cache, counts = _load_cache(cache_path, cache_key) if cache_path else ({}, {})
    selected = list(platforms or DEFAULT_PLATFORMS)
    if manifest is None:
        try:
            manifest = load_manifest()
        except Exception as err:
            logger.info(f"[JobHive] Manifest unavailable ({err}); using the standard file locations.")
            manifest = {}
    urls = platform_urls(selected, manifest)

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(selected)))) as pool:
        futures = {
            pool.submit(_read_platform, urls[platform], opener, cache.get(platform), sleep): platform
            for platform in selected
        }
        done = 0
        for future in as_completed(futures):
            platform = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as err:
                logger.warning(f"[JobHive] {platform}: skipped ({err}). ({done}/{len(selected)})")
                continue
            results[platform] = result
            if result["unchanged"]:
                logger.info(
                    f"[JobHive] {platform}: unchanged since last run ({result['stamp']}); skipped. ({done}/{len(selected)})"
                )
            else:
                logger.info(
                    f"[JobHive] {platform}: {len(result['rows'])} India rows of {result['num_rows']} "
                    f"({result['bytes'] / 1e6:.1f} MB). ({done}/{len(selected)})"
                )

    all_jobs: list[JobRecord] = []
    for platform in selected:  # stable order, whatever finished first
        result = results.get(platform)
        if not result or result["unchanged"]:
            continue
        jobs = rows_to_jobs(result["rows"], platform)
        all_jobs.extend(jobs)
        if result["stamp"]:
            cache[platform] = result["stamp"]
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

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"key": cache_key, "stamps": cache, "counts": counts}, indent=2) + "\n", encoding="utf-8"
        )
    return all_jobs
