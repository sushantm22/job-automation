from __future__ import annotations

from typing import Any


def build_resume_summary(profile: dict[str, Any], role: str = "") -> str:
    personal = profile.get("personal", {})
    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")
    experience = profile.get("experience", [])
    skills = profile.get("skills", [])

    company_names = ", ".join(
        exp.get("company", "") for exp in experience if isinstance(exp, dict) and exp.get("company")
    ) or "previous roles"
    skill_names = ", ".join(skills[:5]) if skills else "backend engineering"
    name = f"{first_name} {last_name}".strip() or "Candidate"
    role_text = role or "software engineering role"

    return (
        f"{name} is a backend-focused engineer with experience across {company_names} and a strong track record "
        f"building scalable systems. Their work centers on {skill_names}, with a focus on reliable APIs, "
        f"distributed workflows, and high-performance systems. They are well-suited for a {role_text} role."
    )
