from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: type[T]) -> T: ...

    def complete_text(self, system: str, user: str) -> str: ...


class MockLLMClient:
    """Simple deterministic client for tests and local development."""

    def __init__(self, response_data: dict[str, Any] | None = None):
        self.response_data = response_data or {}

    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        payload = self.response_data or {}
        try:
            return schema.model_validate(payload)
        except ValidationError:
            defaults: dict[str, Any] = {}
            for name, field in schema.model_fields.items():
                if not field.is_required():
                    defaults[name] = field.default
                    continue

                annotation = field.annotation
                if name == "score":
                    defaults[name] = 0
                elif name == "reason":
                    defaults[name] = "Mock evaluation unavailable"
                elif annotation is list or getattr(annotation, "__origin__", None) is list:
                    defaults[name] = []
                elif annotation is bool:
                    defaults[name] = False
                elif annotation is int:
                    defaults[name] = 0
                elif annotation is float:
                    defaults[name] = 0.0
                elif annotation is str:
                    defaults[name] = ""
                else:
                    defaults[name] = field.default
            return schema.model_validate(defaults)

    def complete_text(self, system: str, user: str) -> str:
        return "mocked response"
