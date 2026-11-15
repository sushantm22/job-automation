from __future__ import annotations

import re
from typing import Any

from .answer_bank import AnswerBank

SENSITIVE_FIELDS = {
    "criminal_history",
    "visa_status",
    "work_authorization",
    "salary",
    "expected_salary",
    "current_ctc",
    "disability_status",
    "gender",
    "ethnicity",
    "veteran_status",
}


def _profile_lookup(profile: dict[str, Any], field_name: str, label: str = "") -> Any:
    if not isinstance(profile, dict):
        return None

    personal = profile.get("personal", {})
    if field_name == "first_name":
        return personal.get("first_name")
    if field_name == "last_name":
        return personal.get("last_name")
    if field_name == "email":
        return personal.get("email")
    if field_name == "phone":
        return personal.get("phone")
    if field_name == "linkedin":
        return personal.get("linkedin")
    if field_name == "github":
        return personal.get("github")
    if field_name == "portfolio":
        return personal.get("portfolio")
    if field_name == "portfolio_url":
        return personal.get("portfolio") or personal.get("website")
    if field_name in {"location", "city", "state", "country"}:
        location = personal.get("location", {})
        return location.get(field_name) or location.get("city") or location.get("country")
    return None


def resolve_form_fields(fields: list[dict[str, Any]], profile: dict[str, Any], answer_bank: AnswerBank | None = None) -> list[dict[str, Any]]:
    if answer_bank is None:
        answer_bank = AnswerBank()

    results: list[dict[str, Any]] = []
    for field in fields:
        field_name = str(field.get("name") or field.get("label") or "").strip()
        label = str(field.get("label") or field_name)
        value = _profile_lookup(profile, field_name, label)
        source = "profile"

        if value is None and answer_bank is not None:
            bank_value = answer_bank.lookup(label) or answer_bank.lookup(field_name)
            if bank_value is not None:
                value = bank_value
                source = "answer_bank"

        if value is None and any(token in re.sub(r"\W+", " ", label.lower()) for token in ["criminal", "convicted", "history", "visa", "sponsorship", "salary", "authorized", "gender", "ethnicity"]):
            results.append({
                "name": field_name,
                "label": label,
                "value": None,
                "source": "needs_human",
                "needs_human": True,
            })
            continue

        if value is None:
            value = None
            source = "needs_human"

        results.append({
            "name": field_name,
            "label": label,
            "value": value,
            "source": source,
            "needs_human": source == "needs_human",
        })

    return results
