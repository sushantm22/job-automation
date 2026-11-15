from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .base import LLMClient

T = TypeVar("T", bound=BaseModel)


class GeminiLLM:
    """Thin wrapper around the Google Gemini API.

    The project keeps the interface generic so other providers can plug in later.
    """

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model

    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        raise NotImplementedError("Gemini integration is scaffolded for M1; actual API call logic will come later.")

    def complete_text(self, system: str, user: str) -> str:
        raise NotImplementedError("Gemini integration is scaffolded for M1; actual API call logic will come later.")


__all__ = ["GeminiLLM", "LLMClient"]
