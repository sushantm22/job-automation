from __future__ import annotations

from typing import Any


def summarize_applications(applications: list[dict[str, Any]]) -> dict[str, float | int]:
    if not applications:
        return {
            "total_applications": 0,
            "average_calls_per_application": 0,
            "average_tokens_per_application": 0,
        }

    total_calls = sum(int(item.get("llm_calls", 0) or 0) for item in applications)
    total_tokens = sum(int(item.get("tokens_in", 0) or 0) + int(item.get("tokens_out", 0) or 0) for item in applications)
    total = len(applications)

    return {
        "total_applications": total,
        "average_calls_per_application": round(total_calls / total, 2),
        "average_tokens_per_application": round(total_tokens / total, 2),
    }
