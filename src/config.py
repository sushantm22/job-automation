from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
DEFAULT_DATABASE_PATH = ROOT / "data" / "jobs.db"


def load_env_file() -> None:
    """Loads the project .env into os.environ without overriding variables already set."""
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        except Exception:
            pass


def resolve_database_path(raw: str | os.PathLike[str] | None = None) -> Path:
    """
    Resolves the SQLite ledger location from a DATABASE_PATH value.
    Empty -> data/jobs.db. Relative paths resolve against the project root (not the
    current working directory), so `DATABASE_PATH=data/alice.db` works from anywhere.
    """
    if raw is None or not str(raw).strip():
        return DEFAULT_DATABASE_PATH
    path = Path(str(raw).strip()).expanduser()
    return path if path.is_absolute() else ROOT / path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_provider: str = Field(default="gemini", validation_alias=AliasChoices("LLM_PROVIDER", "llm_provider"))
    llm_model: str = Field(default="gemini-2.5-flash", validation_alias=AliasChoices("LLM_MODEL", "llm_model"))
    search_keywords: list[str] = Field(default_factory=lambda: ["backend engineer", "python developer"])
    locations: list[str] = Field(default_factory=lambda: ["Remote", "Bengaluru"])
    exclude_keywords: list[str] = Field(default_factory=lambda: ["intern", "unpaid", "10+ years"])
    min_match_score: int = 70
    max_applications_per_day: int = 15
    min_delay_seconds: int = 2
    max_delay_seconds: int = 6
    default_mode: str = Field(default="review", validation_alias=AliasChoices("MODE_DEFAULT", "default_mode"))
    headless: bool = False
    llm_max_calls_per_application: int = 6
    llm_temperature: float = 0.2
    tailoring_enabled: bool = True
    cover_letter_enabled: bool = False
    tier1_direct_apis: bool = True
    tier2_jobspy: bool = True
    tier3_apify: bool = True
    tier4_firecrawl: bool = True
    apify_api_token: str = Field(default="", validation_alias=AliasChoices("APIFY_API_TOKEN", "apify_api_token"))
    apify_actor_id: str = "apify/naukri-scraper"
    firecrawl_api_key: str = Field(default="", validation_alias=AliasChoices("FIRECRAWL_API_KEY", "firecrawl_api_key"))
    enterprise_portals: list[dict[str, str]] = Field(default_factory=list)
    firecrawl_daily_budget: int = 10
    database_path: Path = Field(default=DEFAULT_DATABASE_PATH, validation_alias=AliasChoices("DATABASE_PATH", "database_path"))
    notion_enabled: bool = True
    notion_api_token: str = Field(default="", validation_alias=AliasChoices("NOTION_API_KEY", "notion_api_token"))
    notion_database_id: str = Field(default="", validation_alias=AliasChoices("NOTION_DATABASE_ID", "notion_database_id"))
    notion_parent_page_id: str = Field(default="", validation_alias=AliasChoices("NOTION_PARENT_PAGE_ID", "notion_parent_page_id"))
    notion_auto_sync: bool = True


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return {}
    data = yaml.safe_load(content) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def local_config_path(config_path: Path = CONFIG_PATH) -> Path:
    """Per-user overrides (roles, locations, ...) live next to config.yaml in a gitignored file."""
    return config_path.with_name("config.local.yaml")


def load_settings(config_path: Path = CONFIG_PATH) -> Settings:
    load_env_file()

    # config.yaml holds shared defaults; config.local.yaml (gitignored) holds this user's choices.
    raw = _deep_merge(_read_yaml(config_path), _read_yaml(local_config_path(config_path)))

    search_cfg = raw.get("search", {})
    limits_cfg = raw.get("limits", {})
    mode_cfg = raw.get("mode", {})
    llm_cfg = raw.get("llm", {})
    tailoring_cfg = raw.get("tailoring", {})
    discovery_cfg = raw.get("discovery", {})
    tiers_cfg = discovery_cfg.get("tiers", {})

    merged: dict[str, Any] = {
        "search_keywords": search_cfg.get("keywords", ["backend engineer", "python developer"]),
        "locations": search_cfg.get("locations", ["Remote", "Bengaluru"]),
        "exclude_keywords": search_cfg.get("exclude_keywords", ["intern", "unpaid", "10+ years"]),
        "min_match_score": search_cfg.get("min_match_score", 70),
        "max_applications_per_day": limits_cfg.get("max_applications_per_day", 15),
        "min_delay_seconds": limits_cfg.get("min_delay_seconds", 2),
        "max_delay_seconds": limits_cfg.get("max_delay_seconds", 6),
        "default_mode": mode_cfg.get("default", "review"),
        "headless": mode_cfg.get("headless", False),
        "llm_max_calls_per_application": llm_cfg.get("max_calls_per_application", 6),
        "llm_temperature": llm_cfg.get("temperature", 0.2),
        "tailoring_enabled": tailoring_cfg.get("enabled", True),
        "cover_letter_enabled": tailoring_cfg.get("cover_letter", False),
        "tier1_direct_apis": tiers_cfg.get("tier1_direct_apis", True),
        "tier2_jobspy": tiers_cfg.get("tier2_jobspy", True),
        "tier3_apify": tiers_cfg.get("tier3_apify", True),
        "tier4_firecrawl": tiers_cfg.get("tier4_firecrawl", True),
        "apify_api_token": discovery_cfg.get("apify_api_token", ""),
        "apify_actor_id": discovery_cfg.get("apify_actor_id", "apify/naukri-scraper"),
        "firecrawl_api_key": discovery_cfg.get("firecrawl_api_key", ""),
        "enterprise_portals": discovery_cfg.get("enterprise_portals", []),
        "firecrawl_daily_budget": discovery_cfg.get("firecrawl_daily_budget", 10),
        "notion_enabled": raw.get("notion", {}).get("enabled", True),
        "notion_api_token": raw.get("notion", {}).get("api_token", ""),
        "notion_database_id": raw.get("notion", {}).get("database_id", ""),
        "notion_parent_page_id": raw.get("notion", {}).get("parent_page_id", ""),
        "notion_auto_sync": raw.get("notion", {}).get("auto_sync_on_discover", True),
    }

    env_values = {
        "llm_provider": os.getenv("LLM_PROVIDER"),
        "llm_model": os.getenv("LLM_MODEL"),
        "database_path": resolve_database_path(os.getenv("DATABASE_PATH")) if os.getenv("DATABASE_PATH") else None,
        "apify_api_token": os.getenv("APIFY_API_TOKEN"),
        "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY"),
        "notion_api_token": os.getenv("NOTION_API_KEY"),
        "notion_database_id": os.getenv("NOTION_DATABASE_ID"),
        "notion_parent_page_id": os.getenv("NOTION_PARENT_PAGE_ID"),
    }
    for key, value in list(env_values.items()):
        if value is not None:
            merged[key] = value

    return Settings(**merged)
