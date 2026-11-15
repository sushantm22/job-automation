from __future__ import annotations

from typing import Any


class ReviewGate:
    """Controls the human approval checkpoint before a final application submit."""

    def __init__(self, dry_run: bool = False, auto_submit: bool = False) -> None:
        self.dry_run = dry_run
        self.auto_submit = auto_submit

    def should_submit(self, decision: str) -> bool:
        if self.dry_run:
            return False
        choice = (decision or "").strip().lower()
        return choice in {"s", "submit"}

    def apply_decision(self, page: Any, decision: str) -> bool:
        if self.dry_run:
            return False

        decision_key = (decision or "").strip().lower()
        if decision_key in {"s", "submit"}:
            if hasattr(page, "approved"):
                page.approved = True
            if hasattr(page, "click_submit"):
                page.click_submit()
            return True

        if hasattr(page, "approved"):
            page.approved = False
        if hasattr(page, "submit_clicked"):
            page.submit_clicked = False
        return False


def render_review_table(resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in resolved:
        rows.append(
            {
                "question": item.get("label") or item.get("name") or "unknown",
                "answer": item.get("value"),
                "source": item.get("source") or "unknown",
                "needs_human": bool(item.get("needs_human")),
            }
        )
    return rows
