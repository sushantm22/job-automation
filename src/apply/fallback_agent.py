from __future__ import annotations


class BrowserUseFallbackAgent:
    """Fallback loop that never submits automatically; it only exists for unusual forms."""

    enabled: bool = False
    should_submit: bool = False

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def can_run(self) -> bool:
        return True

    def stop_before_submit(self) -> None:
        self.should_submit = False
