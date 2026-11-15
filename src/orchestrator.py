from __future__ import annotations

from typing import Any

from .apply.review import render_review_table
from .llm.base import MockLLMClient
from .scoring import hard_filter_jobs, score_job


class JobApplicationOrchestrator:
    """Coordinates the deterministic workflow across discovery, scoring, and review."""

    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client or MockLLMClient()

    def discover_jobs(
        self,
        jobs: list[dict[str, Any]],
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return hard_filter_jobs(
            jobs,
            keywords=keywords or [],
            locations=locations or [],
            exclude=exclude or [],
        )

    def score_jobs(
        self,
        jobs: list[dict[str, Any]],
        profile_summary: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for job in jobs:
            result = score_job(job, profile_summary=profile_summary, llm=self.llm_client)
            scored.append({
                "title": job.get("title") or "Unknown role",
                "company": job.get("company") or "Unknown company",
                "location": job.get("location") or "Unknown",
                "url": job.get("url") or "",
                "score": result.score,
                "reason": result.reason,
                "missing_requirements": result.missing_requirements,
                "deal_breakers": result.deal_breakers,
            })
        return scored

    def review_rows(self, resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return render_review_table(resolved)

    def build_application_plan(self, job: dict[str, Any], resolved: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "job": job,
            "resolved_fields": resolved,
            "review_rows": self.review_rows(resolved),
        }
