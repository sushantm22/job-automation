from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib import parse, request

logger = logging.getLogger(__name__)

JUNK_SLUGS = {
    "embed",
    "api",
    "v0",
    "v1",
    "v2",
    "favicon.ico",
    "static",
    "assets",
    "robots.txt",
    "sitemap.xml",
    "search",
    "jobs",
    "job",
    "j",
    "apply",
    "test",
    "demo",
    "careers",
    "company",
    "admin",
    "portal",
    "index",
}

PLATFORM_PATTERNS = [
    {
        "platform": "greenhouse",
        "domains": [r"boards\.greenhouse\.io", r"job-boards\.greenhouse\.io"],
    },
    {
        "platform": "lever",
        "domains": [r"jobs\.lever\.co"],
    },
    {
        "platform": "ashby",
        "domains": [r"jobs\.ashbyhq\.com"],
    },
    {
        "platform": "smartrecruiters",
        "domains": [r"jobs\.smartrecruiters\.com", r"careers\.smartrecruiters\.com"],
    },
]


def extract_ats_slugs(text: str) -> list[dict[str, str]]:
    """
    Extracts all supported ATS platform and slug pairs from arbitrary text, URLs, or HTML.
    Returns a list of dicts: [{'platform': 'greenhouse', 'slug': 'stripe'}, ...]
    """
    if not text:
        return []

    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # 1. Handle Greenhouse embed query pattern: boards.greenhouse.io/embed/job_board?for=company
    embed_matches = re.finditer(
        r"boards\.greenhouse\.io/embed/job_board\?[^\"'\s>]*?for=([A-Za-z0-9_-]+)",
        text,
        re.I,
    )
    for m in embed_matches:
        slug = m.group(1).lower().strip()
        if slug and slug not in JUNK_SLUGS and ("greenhouse", slug) not in seen:
            seen.add(("greenhouse", slug))
            found.append({"platform": "greenhouse", "slug": slug})

    # 2. Handle standard URL path patterns for each ATS domain
    for entry in PLATFORM_PATTERNS:
        platform = entry["platform"]
        for domain_pattern in entry["domains"]:
            regex = re.compile(
                rf"https?://(?:www\.)?{domain_pattern}/([A-Za-z0-9_-]+)",
                re.I,
            )
            for match in regex.finditer(text):
                slug = match.group(1).strip()
                if platform != "smartrecruiters":
                    slug = slug.lower()

                if slug.lower() in JUNK_SLUGS or len(slug) < 2:
                    continue

                key = (platform, slug)
                if key not in seen:
                    seen.add(key)
                    found.append({"platform": platform, "slug": slug})

    return found


def probe_company_board(platform: str, slug: str, timeout: float = 10.0) -> dict[str, Any]:
    """
    Validates a company slug against the official ATS API.
    Returns a dictionary with validation status, name, and current open job count.
    Distinguishes strictly between genuine 404 (defunct) and transient network/DNS errors.
    """
    clean_platform = platform.lower().strip()
    clean_slug = slug.strip()

    result = {
        "valid": False,
        "platform": clean_platform,
        "slug": clean_slug,
        "name": clean_slug.replace("-", " ").replace("_", " ").title(),
        "job_count": 0,
        "status": "unverified",
        "error": None,
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        if clean_platform == "greenhouse":
            url = f"https://boards-api.greenhouse.io/v1/boards/{parse.quote(clean_slug)}/jobs"
            req = request.Request(url, headers=headers)
            with request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                jobs = data.get("jobs") or []
                result["valid"] = True
                result["job_count"] = len(jobs)
                result["status"] = "active"
                if jobs and jobs[0].get("company_name"):
                    result["name"] = jobs[0]["company_name"]

        elif clean_platform == "lever":
            url = f"https://api.lever.co/v0/postings/{parse.quote(clean_slug)}?mode=json"
            req = request.Request(url, headers=headers)
            with request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    result["valid"] = True
                    result["job_count"] = len(data)
                    result["status"] = "active"
                    if data and data[0].get("company"):
                        result["name"] = str(data[0]["company"])

        elif clean_platform == "ashby":
            url = f"https://api.ashbyhq.com/posting-api/job-board/{parse.quote(clean_slug)}"
            req = request.Request(url, headers=headers)
            with request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                jobs = data.get("jobs") or []
                result["valid"] = True
                result["job_count"] = len(jobs)
                result["status"] = "active"

        elif clean_platform == "smartrecruiters":
            # The API returns 200 + totalFound=0 for unknown identifiers, so only a company with
            # postings counts as verified. "empty" (not "not_found") keeps validate-companies from
            # pruning a real company that has no openings right now.
            from .smartrecruiters import fetch_smartrecruiters_page

            data = fetch_smartrecruiters_page(clean_slug, limit=1, country=None, timeout=timeout)
            total = int(data.get("totalFound") or 0)
            if total > 0:
                result["valid"] = True
                result["job_count"] = total
                result["status"] = "active"
                company = ((data.get("content") or [{}])[0].get("company") or {}).get("name")
                if company:
                    result["name"] = company
            else:
                result["status"] = "empty"
                result["error"] = "No postings (unknown identifier or no open roles)"

        else:
            result["error"] = f"Unsupported platform for direct probing: {platform}"
            result["status"] = "unsupported"

    except request.HTTPError as http_err:
        result["error"] = f"HTTP {http_err.code}"
        if http_err.code == 404:
            result["status"] = "not_found"
        elif http_err.code == 429:
            result["status"] = "rate_limited"
        else:
            result["status"] = "http_error"
    except Exception as exc:
        result["error"] = str(exc)
        result["status"] = "network_error"

    return result


def resolve_domain_to_ats(domain_or_url: str, timeout: float = 10.0, verify_live: bool = True) -> list[dict[str, Any]]:
    """
    Given a company domain or career page URL, inspects candidate ATS links, probes candidate slugs,
    and returns verified active boards.
    """
    raw_url = domain_or_url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"

    parsed = parse.urlparse(raw_url)
    hostname = parsed.netloc or parsed.path
    hostname = re.sub(r"^www\.", "", hostname.split(":")[0])

    candidates: list[dict[str, str]] = []

    # 1. First check if the given URL itself already is an ATS link
    direct_slugs = extract_ats_slugs(raw_url)
    if direct_slugs:
        candidates.extend(direct_slugs)
    else:
        # 2. Try fetching the landing or careers page to extract embedded links
        candidate_urls = [
            raw_url,
            f"https://{hostname}/careers",
            f"https://{hostname}/jobs",
            f"https://{hostname}/about/careers",
        ]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        for candidate in candidate_urls:
            try:
                req = request.Request(candidate, headers=headers)
                with request.urlopen(req, timeout=timeout) as resp:
                    final_url = resp.geturl()
                    content = resp.read().decode("utf-8", errors="ignore")

                    # Check final redirect URL
                    from_final_url = extract_ats_slugs(final_url)
                    if from_final_url:
                        candidates.extend(from_final_url)
                        break

                    # Extract any ATS links from the page content
                    from_content = extract_ats_slugs(content)
                    if from_content:
                        candidates.extend(from_content)
                        break
            except Exception:
                continue

        # 3. If no links found in HTML, try probing domain prefix across Greenhouse, Lever, and Ashby
        if not candidates:
            clean_prefix = re.split(r"\.", hostname)[0].lower()
            if len(clean_prefix) >= 3 and clean_prefix not in JUNK_SLUGS:
                for platform in ["greenhouse", "lever", "ashby"]:
                    candidates.append({"platform": platform, "slug": clean_prefix})

    # Deduplicate candidate pairs
    unique_candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for d in candidates:
        key = (d["platform"], d["slug"].lower())
        if key not in seen:
            seen.add(key)
            unique_candidates.append(d)

    if not verify_live:
        return unique_candidates

    # Verify that each candidate is actually active and reachable (not 404 / defunct)
    verified: list[dict[str, Any]] = []
    for item in unique_candidates:
        platform = item["platform"]
        slug = item["slug"]
        probe = probe_company_board(platform, slug, timeout=timeout)
        if probe.get("valid") and probe.get("status") != "not_found":
            verified.append({
                "platform": platform,
                "slug": slug,
                "name": probe.get("name", slug.title()),
                "job_count": probe.get("job_count", 0),
            })

    return verified
