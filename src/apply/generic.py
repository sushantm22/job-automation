from __future__ import annotations

import re
from typing import Any

from src.utils.dom import extract_form_fields


class GenericAdapter:
    def matches(self, url: str) -> bool:
        return bool(url) and not any(
            domain in (url or "").lower()
            for domain in [
                "boards.greenhouse.io",
                "job-boards.greenhouse.io",
                "jobs.lever.co",
                "lever.co",
                "jobs.ashbyhq.com",
                "ashbyhq.com",
            ]
        )

    async def open(self, page: Any, job: dict[str, Any]) -> None:
        if hasattr(page, "goto"):
            await page.goto(job.get("url") or "")

    async def extract_fields(self, page: Any) -> list[dict[str, Any]]:
        if hasattr(page, "content"):
            html = await page.content()
            return extract_form_fields(html or "")
        return []

    async def fill(self, page: Any, resolved: list[dict[str, Any]], review_mode: bool = False) -> bool:
        if review_mode:
            return True

        for item in resolved:
            name = item.get("name") or ""
            value = item.get("value")
            if not name or value is None:
                continue
            if hasattr(page, "locator"):
                locator = page.locator(f"[name='{name}']")
                if hasattr(locator, "fill"):
                    await locator.fill(str(value))
        return True

    async def submit(self, page: Any) -> bool:
        if getattr(page, "approved", True) is False:
            return False
        if hasattr(page, "locator"):
            submit_locator = page.locator("button[type='submit'], input[type='submit']")
            if hasattr(submit_locator, "click"):
                await submit_locator.click()
                return True
        if hasattr(page, "click_submit"):
            page.click_submit()
            return True
        return False

    async def confirm_success(self, page: Any) -> bool:
        if hasattr(page, "content"):
            try:
                html = await page.content()
            except Exception:
                html = ""
            if re.search(r"application submitted|thanks for applying|we received your application", html, re.I):
                return True
        return False
