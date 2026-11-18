from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from .llm.base import LLMClient, MockLLMClient
from .models import JobMatchResult

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
    r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|gurgaon|gurugram|noida|delhi|ncr|chennai|coimbatore|ahmedabad|kolkata|karnataka|maharashtra|tamil nadu|telangana|ka|mh|ts|gj|dl)\b",
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


# --- Role-agnostic title matching -------------------------------------------------------------
# Roles and job titles go through the same normalizer; a job matches when some role form appears
# as a whole-word phrase inside some title form. No list of "business" or "tech" titles anywhere.

# Abbreviations common in Indian job titles. Expanded on both sides, so "BDM" == "Business Development Manager".
_ABBREVIATIONS = {
    "sr": "senior", "snr": "senior", "jr": "junior", "mgr": "manager", "exec": "executive",
    "asst": "assistant", "dy": "deputy",
    "bd": "business development", "bdm": "business development manager",
    "bde": "business development executive", "kam": "key account manager",
    "asm": "area sales manager", "rsm": "regional sales manager", "zsm": "zonal sales manager",
    "tsm": "territory sales manager", "sdr": "sales development representative",
    "bdr": "business development representative", "csm": "customer success manager",
    "hrbp": "hr business partner", "mktg": "marketing", "acct": "account", "ops": "operations",
    "avp": "vp", "svp": "vp", "evp": "vp",
    "gm": "general manager", "agm": "assistant general manager", "dgm": "deputy general manager",
}
_PHRASES = (("human resources", "hr"), ("vice president", "vp"))
# Levels are ignored when matching ("Senior Sales Manager" == "Sales Manager"). Users who don't
# want a level add it to exclude_keywords.
_SENIORITY_WORDS = {"senior", "junior"}
# "Manager - Sales", "Head of Sales": when the part before the separator is only a head noun
# (optionally qualified), the title is also read as "<rest> <head>" ("Sales Manager", "Sales Head").
_HEAD_NOUNS = {
    "manager", "head", "director", "lead", "executive", "officer", "vp", "president", "chief",
    "associate", "analyst", "specialist", "consultant", "coordinator", "representative", "engineer",
}
_HEAD_QUALIFIERS = {"assistant", "deputy", "associate", "general"}
# Separators between title segments: spaced dashes, punctuation, brackets and " of ".
_SEGMENT_SPLIT_RE = re.compile(r"\s[-–—]+\s|[,|:;()\[\]]|\s+of\s+")
# An unspaced hyphen right after a head noun also separates ("Manager-Sales"); elsewhere it is part
# of a word ("E-Commerce", "Walk-in"), see _split_head_hyphens.
_HEAD_HYPHEN_RE = re.compile(r"\b([^\W\d_]+)-(?=[^\W\d_])")
# "Sales & Marketing Manager" also means "Sales Manager" and "Marketing Manager". Both sides need 2+
# letters, so FP&A, L&D, R&D, P&L and M&A stay intact.
_JOINER_RE = re.compile(r"\b([^\W\d_]{2,})\s*[&/]\s*([^\W\d_]{2,})\b")
_WORD_RE = re.compile(r"[^\W_]+")


def _expand_joiners(text: str, limit: int = 3) -> list[str]:
    match = _JOINER_RE.search(text)
    if not match or limit <= 0:
        return [text]
    variants: list[str] = []
    for replacement in (f"{match.group(1)} {match.group(2)}", match.group(1), match.group(2)):
        variants.extend(_expand_joiners(text[:match.start()] + replacement + text[match.end():], limit - 1))
    return variants


def _words(text: str) -> list[str]:
    text = text.lower()
    for phrase, short in _PHRASES:
        text = text.replace(phrase, short)
    words: list[str] = []
    for word in _WORD_RE.findall(text):
        words.extend(_ABBREVIATIONS.get(word, word).split())
    return [w for w in words if w not in _SENIORITY_WORDS and w != "of"]


def _split_head_hyphens(text: str) -> str:
    """ "manager-product category" -> "manager - product category" (only after a head noun)."""
    def spaced(match: re.Match[str]) -> str:
        expanded = _ABBREVIATIONS.get(match.group(1), match.group(1)).split()
        return f"{match.group(1)} - " if expanded and expanded[-1] in _HEAD_NOUNS else match.group(0)

    return _HEAD_HYPHEN_RE.sub(spaced, text)


@lru_cache(maxsize=65536)
def _title_forms(text: str) -> tuple[str, ...]:
    """All normalized readings of a title or role, as space-padded phrases (for whole-word matching)."""
    forms: set[str] = set()
    for variant in _expand_joiners(_split_head_hyphens(text.lower())):
        words = _words(variant)
        if words:
            forms.add(" ".join(words))
        # Reordered readings: wherever a segment is only a head noun (optionally qualified), read it
        # after the next segment ("Manager - Sales" -> "sales manager", "VP - Head of Category" ->
        # "category head"). The next segment ends at the next separator or bracket.
        segments = [w for w in (_words(seg) for seg in _SEGMENT_SPLIT_RE.split(variant)) if w]
        for head, rest in zip(segments, segments[1:]):
            nouns = [w for w in head if w in _HEAD_NOUNS]
            if nouns and all(w in _HEAD_NOUNS or w in _HEAD_QUALIFIERS for w in head):
                forms.add(" ".join(rest + nouns))
                forms.add(" ".join(rest + head))
    return tuple(f" {form} " for form in forms)


def _role_forms(roles: list[str]) -> set[str]:
    return {form for role in roles if role and role.strip() for form in _title_forms(role.strip())}


def _matches_role_forms(title: str, role_forms: set[str]) -> bool:
    return any(role_form in title_form for title_form in _title_forms(title) for role_form in role_forms)


def title_matches_roles(title: str, roles: list[str]) -> bool:
    """True when the job title names one of the user's roles (see the normalizer rules above)."""
    return _matches_role_forms(title, _role_forms(roles))


# Words that say nothing about a job's field ("manager", "senior", "of", ...).
_GENERIC_WORDS = _HEAD_NOUNS | _HEAD_QUALIFIERS | _SENIORITY_WORDS | {
    "of", "and", "the", "for", "in", "at", "to", "with", "on", "ii", "iii", "iv",
}


def related_title_candidates(
    titles: list[str], roles: list[str], exclude: list[str] | None = None, limit: int = 10
) -> list[tuple[str, int]]:
    """
    Close titles worth suggesting as extra roles: titles the job sites returned for the user's
    searches that don't match a role yet but share a field word with one ("Category Lead" for
    "Category Manager"). Ranked by how many roles share their words, then by how often they
    appeared. Returns [(title, count)].
    """
    weights: dict[str, int] = {}
    for role in roles:
        for word in set(_words(role)):
            if len(word) >= 3 and word not in _GENERIC_WORDS:
                weights[word] = weights.get(word, 0) + 1
    if not weights:
        return []
    forms = _role_forms(roles)
    exclude_regex = _exclude_regex(exclude or [])
    groups: dict[str, list[Any]] = {}
    for title in titles:
        text = " ".join(str(title or "").split())
        if not text or (exclude_regex and exclude_regex.search(text)) or _matches_role_forms(text, forms):
            continue
        words = _words(text)
        score = sum(weights.get(w, 0) for w in set(words))
        if not score:
            continue
        group = groups.setdefault(" ".join(words), [text, 0, score])
        group[1] += 1
    ranked = sorted(groups.values(), key=lambda g: (-g[2], -g[1], g[0].lower()))
    return [(text, count) for text, count, _ in ranked[:limit]]


def hard_filter_jobs(
    jobs: list[dict[str, Any]],
    keywords: list[str],
    locations: list[str],
    exclude: list[str],
) -> list[dict[str, Any]]:
    keyword_tokens = [item.lower().strip() for item in keywords if item.strip()]
    location_tokens = [item.lower().strip() for item in locations if item.strip()]
    exclude_regex = _exclude_regex(exclude)
    role_forms = _role_forms(keywords)
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

        # 2. Target role match, on the TITLE only (descriptions mention "sales" or "marketing"
        # in almost every posting, so they say nothing about the role).
        if keyword_tokens:
            role_match = _matches_role_forms(title_str, role_forms)
            # Core QA tokens in the title, only when the user's own roles are QA roles
            if not role_match and targets_qa and QA_TITLE_REGEX.search(title_lower):
                role_match = True
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
