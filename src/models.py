from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobMatchResult(BaseModel):
    score: int = Field(..., ge=0, le=100)
    reason: str
    missing_requirements: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)


class ResolvedField(BaseModel):
    selector: str
    value: Any
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: str = "llm"


class AppProfile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
