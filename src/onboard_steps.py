"""
Non-interactive onboarding steps.

The `setup` wizard asks questions in a terminal, which AI assistants (Claude Code, Cursor,
Codex, Copilot, Gemini CLI) cannot answer. These functions back the `python -m src.cli onboard ...`
commands: each one takes its answers as arguments and never prompts, so an assistant can ask the
user in chat and then run the matching command. See docs/ONBOARDING_PLAYBOOK.md.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Callable

import yaml

from .config import CONFIG_PATH, ROOT, load_settings, local_config_path
from .onboarding import (
    ANSWERS_EXAMPLE_PATH,
    ANSWERS_PATH,
    PROFILE_EXAMPLE_PATH,
    PROFILE_PATH,
    PROFILE_PROMPTS,
    _set_nested,
    ensure_file_from_example,
    load_profile,
    missing_profile_fields,
    read_env_file,
    save_profile,
    test_apify_token,
    test_gemini_key,
    test_notion_key,
    write_env_file,
)

STATE_PATH = ROOT / "data" / "onboarding_state.json"

# Order matters: it is the order an assistant walks the user through.
STEP_ORDER = ["search", "api_keys", "notion", "first_discovery", "profile"]
SKIPPABLE_STEPS = {"api_keys", "notion", "profile"}

# Secrets that `onboard set-key` may write, with an optional online check.
SECRET_KEYS: dict[str, Callable[[str], bool] | None] = {
    "NOTION_API_KEY": test_notion_key,
    "APIFY_API_TOKEN": test_apify_token,
    "FIRECRAWL_API_KEY": None,
    "GEMINI_API_KEY": test_gemini_key,
}

# Friendly field names for `onboard set-profile field=value` -> path inside profile.json.
PROFILE_FIELDS: dict[str, tuple[tuple[str, ...], str]] = {
    keys[-1]: (keys, kind) for keys, _label, kind, _required in PROFILE_PROMPTS
}


# --- state -------------------------------------------------------------------------

def load_state(path: Path | None = None) -> dict[str, str]:
    path = path or STATE_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def mark_step(step: str, value: str = "done", path: Path | None = None) -> None:
    path = path or STATE_PATH
    state = load_state(path)
    state[step] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


# --- status ------------------------------------------------------------------------

def _count_rows(db_path: Path, table: str, where: str = "") -> int:
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(f"SELECT count(*) FROM {table} {where}").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def get_status(config_path: Path | None = None) -> dict[str, Any]:
    """Everything an assistant needs to decide what to ask next. Read-only."""
    from .db import DB_PATH

    config_path = config_path or CONFIG_PATH
    settings = load_settings(config_path)
    env = read_env_file()
    state = load_state(STATE_PATH)
    profile_missing = (
        missing_profile_fields(load_profile(PROFILE_PATH), root=ROOT)
        if PROFILE_PATH.exists() else ["profile.json not created"]
    )
    jobs = _count_rows(DB_PATH, "jobs")
    keys = {name: bool(env.get(name)) for name in SECRET_KEYS}
    local_cfg = local_config_path(config_path)

    steps: dict[str, dict[str, Any]] = {
        "search": {
            "done": state.get("search") == "done",
            "roles": settings.search_keywords,
            "locations": settings.locations,
            "exclude": settings.exclude_keywords,
            "source": "config.local.yaml" if local_cfg.exists() else "config.yaml (shared defaults)",
        },
        "api_keys": {
            "done": state.get("api_keys") in {"done", "skipped"} or any(keys.values()),
            "optional": True,
            "keys_set": keys,
        },
        "notion": {
            "done": bool(env.get("NOTION_DATABASE_ID")) or state.get("notion") == "skipped",
            "optional": True,
            "token_set": keys["NOTION_API_KEY"],
            "table_id_set": bool(env.get("NOTION_DATABASE_ID")),
        },
        "first_discovery": {
            "done": state.get("first_discovery") == "done" or jobs > 0,
            "jobs_stored": jobs,
        },
        "profile": {
            "done": not profile_missing or state.get("profile") == "skipped",
            "optional": True,
            "missing": profile_missing,
            "note": "Needed for applying to jobs, not for discovery.",
        },
    }
    for step_id, info in steps.items():
        if state.get(step_id) == "skipped":
            info["skipped"] = True

    next_step = next((s for s in STEP_ORDER if not steps[s]["done"]), None)
    from . import onboarding

    return {
        "env_file_exists": onboarding.ENV_PATH.exists(),
        "database": str(DB_PATH),
        "registry_boards": _count_rows(DB_PATH, "company_registry", "WHERE status = 'active'"),
        "steps": steps,
        "next_step": next_step,
        "complete": next_step is None,
    }


# --- actions -----------------------------------------------------------------------

def _split_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def set_search(
    roles: str | None = None,
    locations: str | None = None,
    exclude: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Saves the user's search choices to config.local.yaml (gitignored). None = keep current."""
    config_path = config_path or CONFIG_PATH
    local_path = local_config_path(config_path)
    local: dict[str, Any] = {}
    if local_path.exists():
        local = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
    search = local.setdefault("search", {})
    for key, value in (("keywords", roles), ("locations", locations), ("exclude_keywords", exclude)):
        items = _split_list(value)
        if items is not None:
            if not items:
                raise ValueError(f"search {key} cannot be empty")
            search[key] = items
    if not search:
        local.pop("search")
    if local:
        header = "# Your personal overrides of config.yaml (gitignored). Edit freely.\n"
        local_path.write_text(header + yaml.safe_dump(local, sort_keys=False, allow_unicode=True), encoding="utf-8")
    mark_step("search")
    settings = load_settings(config_path)
    return {"roles": settings.search_keywords, "locations": settings.locations, "exclude": settings.exclude_keywords}


def _store_resume(value: str) -> str:
    """Copies a resume from anywhere on disk into data/ (gitignored) and returns its project-relative path."""
    source = Path(value).expanduser()
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        return value  # keep as typed; status will flag it as missing
    try:
        return str(source.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        target = ROOT / "data" / f"resume{source.suffix.lower()}"
        shutil.copyfile(source, target)
        return str(target.relative_to(ROOT))


def set_profile(updates: dict[str, str]) -> dict[str, Any]:
    """Applies `field=value` updates to data/profile.json, creating it from the example first."""
    unknown = sorted(set(updates) - set(PROFILE_FIELDS))
    if unknown:
        raise ValueError(f"Unknown profile field(s): {', '.join(unknown)}. Allowed: {', '.join(PROFILE_FIELDS)}")
    ensure_file_from_example(PROFILE_PATH, PROFILE_EXAMPLE_PATH)
    ensure_file_from_example(ANSWERS_PATH, ANSWERS_EXAMPLE_PATH)
    profile = load_profile(PROFILE_PATH)
    for field, raw in updates.items():
        keys, kind = PROFILE_FIELDS[field]
        value: Any = raw.strip()
        if kind == "int":
            value = int(value or 0)
        elif field == "resume" and value:
            value = _store_resume(value)
        _set_nested(profile, keys, value)
    save_profile(profile, PROFILE_PATH)
    return {"missing": missing_profile_fields(profile, root=ROOT), "resume": profile.get("files", {}).get("resume")}


def set_key(name: str, value: str, verify: bool = True) -> dict[str, Any]:
    """Saves a secret to .env (never echoed). Returns whether an online check passed (None = no check)."""
    if name not in SECRET_KEYS:
        raise ValueError(f"Unknown key {name}. Allowed: {', '.join(SECRET_KEYS)}")
    value = (value or "").strip()
    if not value:
        raise ValueError("Empty value: nothing saved.")
    write_env_file({name: value})
    checker = SECRET_KEYS[name]
    verified = checker(value) if (verify and checker) else None
    return {"saved": name, "verified": verified}


def prepare() -> dict[str, Any]:
    """
    Step 0, run before asking the user anything: make sure .env exists (from .env.example) so the
    user can add keys to it themselves, create the database, and load the company registry.
    Safe to run repeatedly.
    """
    from . import onboarding
    from .db import DB_PATH, init_db
    from .discovery.registry import CompanyRegistry

    env_created = ensure_file_from_example(onboarding.ENV_PATH, onboarding.ENV_EXAMPLE_PATH)
    if not onboarding.ENV_PATH.exists():  # no template available: still give the user a file to edit
        onboarding.ENV_PATH.write_text("# Local secrets (gitignored)\n", encoding="utf-8")
        env_created = True
    db_path = init_db(DB_PATH)
    registry = CompanyRegistry(db_path=db_path)
    seeded = registry.ensure_seeded()
    return {
        "env_file": str(onboarding.ENV_PATH),
        "env_created": env_created,
        "database": str(db_path),
        "registry_seeded": seeded,
        "registry_boards": registry.get_stats().get("active_companies", 0),
    }


def check_keys() -> dict[str, str]:
    """Checks every known key in .env online where possible. Returns name -> status; never returns values."""
    env = read_env_file()
    results: dict[str, str] = {}
    for name, checker in SECRET_KEYS.items():
        value = (env.get(name) or "").strip()
        if not value:
            results[name] = "missing"
        elif checker is None:
            results[name] = "set (no online check)"
        else:
            results[name] = "verified" if checker(value) else "failed"
    return results


def skip_step(step: str) -> None:
    if step not in SKIPPABLE_STEPS:
        raise ValueError(f"'{step}' cannot be skipped. Skippable: {', '.join(sorted(SKIPPABLE_STEPS))}")
    mark_step(step, "skipped")
