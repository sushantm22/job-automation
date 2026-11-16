from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .llm.base import LLMClient, MockLLMClient
from .models import JobMatchResult


import re

FOREIGN_REGIONS = [
    r"\b(us|usa|united states|u\.s\.|u\.s\.a\.)\b",
    r"\b(uk|united kingdom|london|england|scotland)\b",
    r"\b(canada|toronto|vancouver|montreal|ontario)\b",
    r"\b(japan|tokyo|kyoto|osaka)\b",
    r"\b(germany|berlin|munich|frankfurt)\b",
    r"\b(korea|seoul)\b",
    r"\b(singapore)\b",
    r"\b(australia|sydney|melbourne)\b",
    r"\b(costa rica|serbia|belgrade|brazil|france|paris|netherlands|amsterdam|ireland|dublin|poland)\b",
    r"\b(california|san francisco|new york|texas|austin|washington|seattle|colorado|georgia|virginia|maryland|oregon|ohio|chicago|boston)\b",
]
FOREIGN_LOCATION_REGEX = re.compile("|".join(FOREIGN_REGIONS), re.IGNORECASE)

INDIA_LOCATION_REGEX = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|gurgaon|gurugram|noida|delhi|ncr|chennai|coimbatore|ahmedabad|kolkata|karnataka|maharashtra|tamil nadu|telangana|ka|mh|tn|ts|gj|dl)\b",
    re.IGNORECASE,
)
GENERIC_REMOTE_REGEX = re.compile(r"\b(remote|anywhere|worldwide)\b", re.IGNORECASE)


def _exclude_regex(exclude: list[str]) -> re.Pattern[str] | None:
    """
    Builds a whole-word matcher for exclude keywords. A plain substring check made
    "intern" reject any JD mentioning "international" or "internal". The optional
    "ship(s)" suffix keeps "intern" catching "Internship" titles.
    """
    tokens = [item.lower().strip() for item in exclude if item and item.strip()]
    if not tokens:
        return None
    alternatives = "|".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?:ships?)?(?!\w)", re.IGNORECASE)


# Core QA/SDET title tokens. Used as a title fallback only when the user's own roles are QA roles.
QA_TITLE_REGEX = re.compile(
    "|".join([
        r"\bsdet\b",
        r"\bqa\b",
        r"\bquality\s+(engineering|engineer|analyst)\b",
        r"\bsoftware\s+(engineer|developer)\s+in\s+test\b",
        r"\b(test\s+automation|automation\s+test|automation\s+engineer)\b",
        r"\b(test\s+lead|qa\s+lead|qa\s+manager)\b",
    ]),
    re.IGNORECASE,
)


def _title_matches_roles(title_lower: str, keyword_tokens: list[str]) -> bool:
    for kw in keyword_tokens:
        if len(kw) <= 4:
            if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
                return True
        elif kw in title_lower:
            return True
    return False


def hard_filter_jobs(
    jobs: list[dict[str, Any]],
    keywords: list[str],
    locations: list[str],
    exclude: list[str],
) -> list[dict[str, Any]]:
    keyword_tokens = [item.lower().strip() for item in keywords if item.strip()]
    location_tokens = [item.lower().strip() for item in locations if item.strip()]
    exclude_regex = _exclude_regex(exclude)

    # Unrelated corporate non-technical/non-QA titles, rejected unless the title matches a user role
    unrelated_title_patterns = [
        r"\b(account executive|sales director|sales manager|gtm recruiter|talent sourcer|head of marketing|marketing manager|accounting manager|delivery solutions architect|solutions architect)\b",
    ]
    unrelated_title_regex = re.compile("|".join(unrelated_title_patterns), re.IGNORECASE)
    targets_qa = any(QA_TITLE_REGEX.search(kw) for kw in keyword_tokens)

    filtered: list[dict[str, Any]] = []
    for job in jobs:
        title_str = str(job.get("title") or "").strip()
        title_lower = title_str.lower()
        loc_str = str(job.get("location") or "").strip()
        loc_lower = loc_str.lower()
        desc_str = str(job.get("description") or "").strip().lower()

        # 1. Exclude keywords check across text blob (whole-word, see _exclude_regex)
        text_blob = f"{title_lower} {loc_lower} {desc_str}"
        if exclude_regex and exclude_regex.search(text_blob):
            continue

        # 2. Target role match on the title (strong match). A title naming one of the
        # user's own roles is always kept, even if it is on the unrelated list below.
        title_match = _title_matches_roles(title_lower, keyword_tokens)

        # 3. Reject obvious unrelated titles (e.g. Sales, Accounting, Recruiter) unless
        # the user explicitly targets that role.
        if not title_match and unrelated_title_regex.search(title_lower):
            continue

        # 4. Target Role Match (Title or Description match)
        role_match = title_match
        if keyword_tokens:
            # Fallback to core QA tokens in the title, only when the user targets QA roles
            if not role_match and targets_qa and QA_TITLE_REGEX.search(title_lower):
                role_match = True

            # If still not matched, allow description match ONLY if title is engineering/technical
            if not role_match and desc_str:
                for kw in keyword_tokens:
                    if len(kw) <= 4:
                        if re.search(r"\b" + re.escape(kw) + r"\b", desc_str):
                            role_match = True
                            break
                    elif kw in desc_str:
                        role_match = True
                        break

            if not role_match:
                continue

        # 5. Strict Location Match (Must be India or Remote, and NOT foreign-only)
        if location_tokens:
            # If location has foreign country/city and no mention of India, reject
            if FOREIGN_LOCATION_REGEX.search(loc_lower) and not INDIA_LOCATION_REGEX.search(loc_lower):
                continue

            # Must match India location or generic Remote
            loc_match = False
            if INDIA_LOCATION_REGEX.search(loc_lower):
                loc_match = True
            elif GENERIC_REMOTE_REGEX.search(loc_lower):
                # Generic remote allowed only if not restricted to foreign regions
                loc_match = True
            else:
                # Check user location tokens with word boundary
                for lt in location_tokens:
                    if re.search(r"\b" + re.escape(lt) + r"\b", loc_lower):
                        loc_match = True
                        break

            if not loc_match:
                continue

        filtered.append(job)

    return filtered


def score_job(job: dict[str, Any], profile_summary: dict[str, Any] | None = None, llm: LLMClient | None = None) -> JobMatchResult:
    if llm is None:
        llm = MockLLMClient()

    system = (
        "You are a job-match evaluator. Use only the facts in the profile and the job description. "
        "Return JSON only with score, reason, missing_requirements, and deal_breakers."
    )
    user = json.dumps({"job": job, "profile": profile_summary or {}})

    result = llm.complete_json(system, user, JobMatchResult)
    return result
