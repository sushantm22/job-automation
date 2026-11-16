from __future__ import annotations

import os
import re
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .utils.net import never_reached_server

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
PROFILE_PATH = ROOT / "data" / "profile.json"
PROFILE_EXAMPLE_PATH = ROOT / "data" / "profile.example.json"
ANSWERS_PATH = ROOT / "data" / "candidate_answers_reference.json"
ANSWERS_EXAMPLE_PATH = ROOT / "data" / "candidate_answers.example.json"

NOTION_CONNECT_TIP = (
    "\nTip: Notion only lets an integration see pages you explicitly share with it:\n"
    "  1. Open the parent page in Notion\n"
    "  2. Click '...' (top-right) -> 'Connections' -> select your integration\n"
    "  3. Re-run: python -m src.cli init-notion-db --parent-page-id <page URL or ID>"
)

# (path in profile.json, prompt label, kind, required-for-applications)
PROFILE_PROMPTS: list[tuple[tuple[str, ...], str, str, bool]] = [
    (("personal", "first_name"), "First name", "str", True),
    (("personal", "last_name"), "Last name", "str", True),
    (("personal", "email"), "Email", "str", True),
    (("personal", "phone"), "Phone (with country code, e.g. +91 ...)", "str", True),
    (("personal", "location", "city"), "City", "str", True),
    (("personal", "location", "country"), "Country", "str", True),
    (("personal", "linkedin"), "LinkedIn URL", "str", True),
    (("personal", "github"), "GitHub URL (optional)", "str", False),
    (("preferences", "notice_period_days"), "Notice period in days", "int", False),
    (("files", "resume"), "Resume file path (relative to the project folder)", "str", True),
]

console = Console()


def ensure_file_from_example(path: Path, example_path: Path) -> bool:
    """Creates a gitignored personal file from its tracked example if missing. Returns True if created."""
    if path.exists() or not example_path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _get_nested(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _set_nested(data: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def load_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_profile(profile: dict[str, Any], path: Path = PROFILE_PATH) -> None:
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def missing_profile_fields(profile: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Labels of required profile fields that are empty, plus the resume if its file doesn't exist."""
    missing: list[str] = []
    for keys, label, _kind, required in PROFILE_PROMPTS:
        if not required:
            continue
        value = _get_nested(profile, keys)
        if value in (None, ""):
            missing.append(label)
        elif keys == ("files", "resume") and not (root / str(value)).exists():
            missing.append(f"{label} (file not found: {value})")
    return missing


def provision_notion_table(
    api_token: str,
    parent_page_id: str,
    title: str = "Job Opportunities",
) -> tuple[dict[str, str], str]:
    """Creates the jobs table under the parent page. Returns (.env values to save, table URL)."""
    from .integrations.notion_client import clean_notion_id, create_notion_job_database

    res = create_notion_job_database(parent_page_id=parent_page_id, title=title, api_token=api_token)
    env_values = {
        "NOTION_DATABASE_ID": clean_notion_id(res["id"]),
        "NOTION_PARENT_PAGE_ID": clean_notion_id(parent_page_id),
    }
    return env_values, res.get("url") or ""


def _ask(label: str, current: Any = "") -> str:
    """Prompt that shows the current value as the default and returns '' when left empty."""
    current_str = "" if current in (None, "") else str(current)
    answer = Prompt.ask(label, default=current_str) if current_str else Prompt.ask(label)
    return (answer or "").strip()


def run_profile_step() -> None:
    """Wizard step: create data/profile.json from the example and fill the basics."""
    if ensure_file_from_example(PROFILE_PATH, PROFILE_EXAMPLE_PATH):
        console.print("[green]✔ Created data/profile.json from the example (gitignored — stays on your machine).[/green]")
    profile = load_profile()
    missing = missing_profile_fields(profile)
    if missing:
        console.print(f"[yellow]Missing profile fields:[/yellow] {', '.join(missing)}")
    else:
        console.print("[green]✔ Your basic profile is complete.[/green]")

    if Confirm.ask("\nWould you like to fill in your basic profile now?", default=bool(missing)):
        for keys, label, kind, _required in PROFILE_PROMPTS:
            answer = _ask(f"   {label}", _get_nested(profile, keys))
            if kind == "int":
                try:
                    _set_nested(profile, keys, int(answer or 0))
                except ValueError:
                    console.print(f"   [yellow]'{answer}' is not a number; keeping the previous value.[/yellow]")
            else:
                _set_nested(profile, keys, answer)
        save_profile(profile)
        console.print("[green]✔ Saved data/profile.json.[/green]")
        still_missing = missing_profile_fields(profile)
        if still_missing:
            console.print(f"[yellow]Still missing:[/yellow] {', '.join(still_missing)}")

    if ensure_file_from_example(ANSWERS_PATH, ANSWERS_EXAMPLE_PATH):
        console.print("[green]✔ Created data/candidate_answers_reference.json from the example (gitignored).[/green]")
    console.print(
        "[dim]Add experience, education and skills by editing data/profile.json, and your answers to common "
        "screening questions (CTC, notice period, etc.) in data/candidate_answers_reference.json.[/dim]"
    )


def check_environment() -> dict[str, Any]:
    """Checks Python version, virtualenv, and local directory setup."""
    is_venv = sys.prefix != sys.base_prefix
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    valid_version = sys.version_info >= (3, 10)
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return {
        "python_version": py_version,
        "valid_version": valid_version,
        "is_venv": is_venv,
        "has_env_file": ENV_PATH.exists(),
    }


def read_env_file() -> dict[str, str]:
    """
    Reads current key-value pairs from .env without exposing them. Uses python-dotenv,
    the same parser the app uses at runtime, so inline comments (`KEY=  # note`) and
    quotes are handled identically instead of being read as values.
    """
    if not ENV_PATH.exists():
        return {}
    from dotenv import dotenv_values

    return {k: (v or "").strip() for k, v in dotenv_values(ENV_PATH).items() if k}


def write_env_file(env_vars: dict[str, str]) -> None:
    """Safely updates .env while maintaining existing keys. An empty value removes the key."""
    existing = read_env_file()
    existing.update(env_vars)
    existing = {k: v for k, v in existing.items() if v not in (None, "")}

    lines = [
        "# ==============================================================================",
        "# Job Application Automation - Environment Configuration",
        "# Keep this file local and NEVER commit to GitHub!",
        "# ==============================================================================",
    ]
    for k, v in existing.items():
        lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_secret(secret: str) -> str:
    """Masks secret showing only first 4 and last 4 characters."""
    if not secret:
        return "[dim]None[/dim]"
    if len(secret) <= 8:
        return "********"
    return f"{secret[:4]}...{secret[-4:]}"


def test_gemini_key(api_key: str) -> bool | None:
    """Quick validation check for Google Gemini API key."""
    if not api_key:
        return False
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as err:
        # None = couldn't check (offline / sandboxed), which says nothing about the key itself.
        return None if never_reached_server(err) else False


def test_apify_token(token: str) -> bool | None:
    """Quick validation check for Apify API token."""
    if not token:
        return False
    try:
        url = f"https://api.apify.com/v2/users/me?token={token}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as err:
        # None = couldn't check (offline / sandboxed), which says nothing about the key itself.
        return None if never_reached_server(err) else False


def test_notion_key(token: str) -> bool | None:
    """Quick validation check for Notion Integration API token."""
    if not token:
        return False
    try:
        url = "https://api.notion.com/v1/users/me"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as err:
        # None = couldn't check (offline / sandboxed), which says nothing about the key itself.
        return None if never_reached_server(err) else False


def run_interactive_onboarding() -> None:
    """Runs the step-by-step interactive onboarding agent."""
    console.print("\n")
    console.print(
        Panel.fit(
            "[bold cyan]🤖 Job Application Automation — Onboarding & Setup Agent[/bold cyan]\n"
            "[white]This wizard will guide you through configuring your target roles, credentials, and local database.[/white]",
            border_style="cyan",
        )
    )

    env_info = check_environment()
    if not env_info["valid_version"]:
        console.print(f"[bold red]❌ Python 3.10+ required. Current: {env_info['python_version']}[/bold red]")
        return
    if not env_info["is_venv"]:
        console.print("[yellow]⚠️ Notice: You are not running inside a virtual environment. We recommend activating .venv.[/yellow]\n")

    current_env = read_env_file()

    # Step 1: Role Configuration
    console.print("\n[bold green]Step 1: Target Roles & Locations[/bold green]")
    from .config import load_settings
    from .onboard_steps import set_search

    current_settings = load_settings()
    current_keywords = current_settings.search_keywords
    current_locations = current_settings.locations

    console.print(f"Current Target Roles: [cyan]{', '.join(current_keywords)}[/cyan]")
    console.print(f"Current Locations: [cyan]{', '.join(current_locations)}[/cyan]")

    if Confirm.ask("\nWould you like to customize your target roles and locations?", default=False):
        new_roles_input = Prompt.ask(
            "Enter comma-separated target roles",
            default=", ".join(current_keywords),
        )
        new_keywords = [r.strip() for r in new_roles_input.split(",") if r.strip()]

        new_locs_input = Prompt.ask(
            "Enter comma-separated target locations",
            default=", ".join(current_locations),
        )
        new_locations = [l.strip() for l in new_locs_input.split(",") if l.strip()]

        set_search(roles=", ".join(new_keywords), locations=", ".join(new_locations))
        console.print("[green]✔ Saved to config.local.yaml (your personal settings, gitignored).[/green]")
    else:
        set_search()  # keeping the defaults counts as a decision

    # Step 2: Candidate Profile
    console.print("\n[bold green]Step 2: Candidate Profile[/bold green]")
    run_profile_step()

    # Step 3: Credentials & Free Tiers Explanation
    console.print("\n[bold green]Step 3: API Keys & Credentials[/bold green]")
    console.print(
        Panel(
            "[bold white]✨ Free & Zero-Setup Tiers:[/bold white]\n"
            "• [cyan]Tier 1 (Direct ATS APIs):[/cyan] Greenhouse, Lever, Ashby — [bold green]100% Free, NO API keys required![/bold green]\n"
            "• [cyan]Tier 2 (JobSpy Aggregators):[/cyan] LinkedIn, Indeed, Glassdoor — [bold green]100% Free, NO API keys required![/bold green]\n\n"
            "[dim]Optional Tiers / Integrations require keys (stored safely in .env, never pushed to git).[/dim]",
            border_style="green",
        )
    )

    new_env_vars: dict[str, str] = {}

    # LLM Key (Gemini)
    current_gemini = current_env.get("GEMINI_API_KEY", "")
    console.print(
        "\n[bold]1. Gemini API Key[/bold] (Optional, [yellow]not used yet[/yellow]: AI job scoring and resume "
        "tailoring are planned. Free from [link=https://aistudio.google.com/]Google AI Studio[/link]):"
    )
    console.print(f"   Current Key: {mask_secret(current_gemini)}")
    if Confirm.ask("   Do you want to set a Gemini API Key now?", default=False):
        gemini_input = Prompt.ask("   Paste your GEMINI_API_KEY (leave empty to skip)", password=True)
        if gemini_input.strip():
            with console.status("   Verifying Gemini key..."):
                if test_gemini_key(gemini_input.strip()):
                    console.print("   [green]✔ Gemini API Key verified successfully![/green]")
                    new_env_vars["GEMINI_API_KEY"] = gemini_input.strip()
                    new_env_vars["LLM_PROVIDER"] = "gemini"
                else:
                    console.print("   [yellow]⚠️ Could not verify key online. Saving anyway.[/yellow]")
                    new_env_vars["GEMINI_API_KEY"] = gemini_input.strip()

    # Tier 3 (Apify)
    current_apify = current_env.get("APIFY_API_TOKEN", "")
    console.print(f"\n[bold]2. Apify API Token[/bold] (Optional: Tier 3 Naukri cloud anti-bot scraping):")
    console.print(f"   Current Token: {mask_secret(current_apify)}")
    if Confirm.ask("   Do you want to update your Apify API Token?", default=not bool(current_apify)):
        apify_input = Prompt.ask("   Paste your APIFY_API_TOKEN (leave empty to skip)", password=True)
        if apify_input.strip():
            with console.status("   Verifying Apify token..."):
                if test_apify_token(apify_input.strip()):
                    console.print("   [green]✔ Apify Token verified successfully![/green]")
                    new_env_vars["APIFY_API_TOKEN"] = apify_input.strip()
                else:
                    console.print("   [yellow]⚠️ Could not verify token online. Saving anyway.[/yellow]")
                    new_env_vars["APIFY_API_TOKEN"] = apify_input.strip()

    # Tier 4 (Firecrawl)
    current_fc = current_env.get("FIRECRAWL_API_KEY", "")
    console.print(f"\n[bold]3. Firecrawl API Key[/bold] (Optional: Tier 4 Apple/Netflix enterprise portal crawler):")
    console.print(f"   Current Key: {mask_secret(current_fc)}")
    if Confirm.ask("   Do you want to update your Firecrawl API Key?", default=not bool(current_fc)):
        fc_input = Prompt.ask("   Paste your FIRECRAWL_API_KEY (leave empty to skip)", password=True)
        if fc_input.strip():
            new_env_vars["FIRECRAWL_API_KEY"] = fc_input.strip()
            console.print("   [green]✔ Firecrawl Key configured.[/green]")

    # Notion Integration
    current_notion = current_env.get("NOTION_API_KEY", "")
    notion_token = current_notion
    console.print(f"\n[bold]4. Notion Integration[/bold] (Optional: for tabular database tracking):")
    console.print(f"   Current Token: {mask_secret(current_notion)}")
    if Confirm.ask("   Do you want to configure Notion Table Sync?", default=not bool(current_notion)):
        notion_input = Prompt.ask("   Paste your NOTION_API_KEY (starts with ntn_)", password=True)
        if notion_input.strip():
            notion_token = notion_input.strip()
            new_env_vars["NOTION_API_KEY"] = notion_token
            with console.status("   Verifying Notion token..."):
                verified = test_notion_key(notion_token)
            if verified:
                console.print("   [green]✔ Notion Integration Token verified![/green]")
            else:
                console.print("   [yellow]⚠️ Could not verify Notion token. Saving anyway.[/yellow]")

    if notion_token:
        from .integrations.notion_client import clean_notion_id

        existing_db = current_env.get("NOTION_DATABASE_ID", "")
        if existing_db and Confirm.ask("   A Notion jobs table is already configured. Keep using it?", default=True):
            console.print("   [green]✔ Keeping your existing Notion table.[/green]")
        elif Confirm.ask("   Create your Notion jobs table now?", default=True):
            parent_input = _ask(
                "   Paste the Notion parent page URL or ID (the page you connected your integration to)",
                current_env.get("NOTION_PARENT_PAGE_ID", ""),
            )
            if parent_input:
                new_env_vars["NOTION_PARENT_PAGE_ID"] = clean_notion_id(parent_input)
                try:
                    with console.status("   Creating Notion table..."):
                        notion_env, table_url = provision_notion_table(notion_token, parent_input)
                    new_env_vars.update(notion_env)
                    console.print(f"   [green]✔ Notion table created:[/green] {table_url}")
                except Exception as err:
                    from .integrations.notion_client import explain_notion_error
                    message, sharing_problem = explain_notion_error(err)
                    console.print(f"   [red]❌ Could not create the Notion table: {message}[/red]")
                    if sharing_problem:
                        console.print(NOTION_CONNECT_TIP)

    # Database Path
    new_env_vars.setdefault("DATABASE_PATH", current_env.get("DATABASE_PATH", "data/jobs.db"))

    # Save to .env
    write_env_file(new_env_vars)
    console.print("\n[bold green]✔ Credentials saved securely to .env (strictly excluded from git).[/bold green]")

    # Step 4: Database, Company Registry & Ready Check
    console.print("\n[bold green]Step 4: Database & Pipeline Verification[/bold green]")
    from .db import init_db
    from .discovery.registry import CompanyRegistry

    db_path = init_db()
    console.print(f"✔ SQLite Ledger active at [cyan]{db_path}[/cyan]")
    registry = CompanyRegistry(db_path=db_path)
    seeded = registry.ensure_seeded()
    if seeded:
        console.print(f"✔ Loaded [cyan]{seeded}[/cyan] company boards from companies.yaml into your registry.")
    active_boards = registry.get_stats().get("active_companies", 0)

    # Setup summary table
    table = Table(title="Configuration Summary")
    table.add_column("Service / Tier", style="cyan")
    table.add_column("Status", style="white")

    updated_env = read_env_file()
    profile_missing = missing_profile_fields(load_profile())
    table.add_row("Candidate Profile (data/profile.json)", "[green]Complete[/green]" if not profile_missing else f"[yellow]{len(profile_missing)} field(s) missing[/yellow]")
    table.add_row("Tier 1: Direct APIs (Greenhouse/Lever/Ashby/SmartRecruiters)", f"[bold green]Active: {active_boards} company boards (Free)[/bold green]" if active_boards else "[yellow]No company boards in registry[/yellow]")
    table.add_row("Tier 2: JobSpy (LinkedIn/Indeed/Glassdoor/Naukri)", "[bold green]Active (Free, No Key Required)[/bold green]")
    table.add_row("Tier 3: Apify Naukri (fallback)", "[green]Configured[/green]" if updated_env.get("APIFY_API_TOKEN") else "[dim]Disabled (Optional)[/dim]")
    table.add_row("Tier 4: Firecrawl Enterprise Portals", "[green]Configured[/green]" if updated_env.get("FIRECRAWL_API_KEY") else "[dim]Disabled (Optional)[/dim]")
    if updated_env.get("NOTION_API_KEY") and updated_env.get("NOTION_DATABASE_ID"):
        notion_status = "[green]Configured (table ready)[/green]"
    elif updated_env.get("NOTION_API_KEY"):
        notion_status = "[yellow]Token set, no table yet: run init-notion-db[/yellow]"
    else:
        notion_status = "[dim]Disabled (Optional)[/dim]"
    table.add_row("Notion Tabular Sync", notion_status)
    table.add_row("LLM Scoring & Tailoring", "[dim]Not available yet (planned)[/dim]")
    console.print(table)

    console.print(
        Panel(
            "[bold green]🎉 You are ready to start discovering jobs![/bold green]\n\n"
            "Run discovery across all active tiers:\n"
            "  [bold cyan]python -m src.cli discover[/bold cyan]\n\n"
            "Reset your local database to clean slate anytime:\n"
            "  [bold cyan]python -m src.cli reset-db[/bold cyan]\n\n"
            "Verify zero secrets are exposed before pushing to git:\n"
            "  [bold cyan]python -m src.cli verify-secrets[/bold cyan]",
            border_style="green",
        )
    )


def audit_tracked_secrets() -> list[dict[str, str]]:
    """
    Scans all git-tracked files to ensure no live API tokens or credentials
    are accidentally exposed or committed.
    """
    import subprocess

    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        tracked_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        # Fallback if git not in PATH
        tracked_files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in str(p)]

    # Regex patterns for sensitive tokens
    patterns = [
        ("Notion Token", re.compile(r"ntn_[a-zA-Z0-9]{30,}")),
        ("Firecrawl Key", re.compile(r"fc-[a-zA-Z0-9]{25,}")),
        ("Apify Token", re.compile(r"apify_api_[a-zA-Z0-9]{25,}")),
        ("Google AI API Key", re.compile(r"AIza[0-9A-Za-z-_]{35}")),
        ("OpenAI Key", re.compile(r"sk-[a-zA-Z0-9]{32,}")),
    ]

    violations: list[dict[str, str]] = []

    for rel_path in tracked_files:
        full_path = ROOT / rel_path
        if not full_path.exists() or full_path.is_dir():
            continue
        # Skip binary files or lock files
        if full_path.suffix in [".db", ".bak", ".png", ".jpg", ".pyc"]:
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for token_type, pat in patterns:
            for match in pat.finditer(content):
                val = match.group(0)
                # Ignore obvious mock test tokens
                if "fake" in val or "test" in val or "12345" in val:
                    continue
                violations.append({
                    "file": rel_path,
                    "type": token_type,
                    "snippet": mask_secret(val),
                })

    return violations
