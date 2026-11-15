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

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

console = Console()


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
    """Reads current key-value pairs from .env without exposing them."""
    env_vars: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env_vars
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars


def write_env_file(env_vars: dict[str, str]) -> None:
    """Safely updates .env while maintaining existing keys."""
    existing = read_env_file()
    existing.update(env_vars)

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


def test_gemini_key(api_key: str) -> bool:
    """Quick validation check for Google Gemini API key."""
    if not api_key:
        return False
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False


def test_apify_token(token: str) -> bool:
    """Quick validation check for Apify API token."""
    if not token:
        return False
    try:
        url = f"https://api.apify.com/v2/users/me?token={token}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False


def test_notion_key(token: str) -> bool:
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
    except Exception:
        return False


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
    config_data = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

    current_keywords = config_data.get("search", {}).get("keywords", ["SDET", "QA Automation Engineer"])
    current_locations = config_data.get("search", {}).get("locations", ["India", "Remote", "Bengaluru"])

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

        config_data.setdefault("search", {})["keywords"] = new_keywords
        config_data.setdefault("search", {})["locations"] = new_locations
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f, sort_keys=False)
        console.print("[green]✔ Updated config.yaml successfully.[/green]")

    # Step 2: Credentials & Free Tiers Explanation
    console.print("\n[bold green]Step 2: API Keys & Credentials[/bold green]")
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
    console.print(f"\n[bold]1. Gemini API Key[/bold] (for resume tailoring & form evaluation, free from [link=https://aistudio.google.com/]Google AI Studio[/link]):")
    console.print(f"   Current Key: {mask_secret(current_gemini)}")
    if Confirm.ask("   Do you want to update your Gemini API Key?", default=not bool(current_gemini)):
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
    console.print(f"\n[bold]4. Notion Integration[/bold] (Optional: for tabular database tracking):")
    console.print(f"   Current Token: {mask_secret(current_notion)}")
    if Confirm.ask("   Do you want to configure Notion Table Sync?", default=not bool(current_notion)):
        notion_input = Prompt.ask("   Paste your NOTION_API_KEY (starts with ntn_)", password=True)
        if notion_input.strip():
            with console.status("   Verifying Notion token..."):
                if test_notion_key(notion_input.strip()):
                    console.print("   [green]✔ Notion Integration Token verified![/green]")
                    new_env_vars["NOTION_API_KEY"] = notion_input.strip()
                    parent_input = Prompt.ask("   Paste your Notion Parent Page URL or ID")
                    if parent_input.strip():
                        # Extract 32-char ID if URL
                        clean_id = parent_input.strip().split("?")[0].split("-")[-1].replace("/", "")
                        new_env_vars["NOTION_PARENT_PAGE_ID"] = clean_id
                else:
                    console.print("   [yellow]⚠️ Could not verify Notion token. Saving anyway.[/yellow]")
                    new_env_vars["NOTION_API_KEY"] = notion_input.strip()

    # Database Path
    new_env_vars.setdefault("DATABASE_PATH", current_env.get("DATABASE_PATH", "data/jobs.db"))

    # Save to .env
    write_env_file(new_env_vars)
    console.print("\n[bold green]✔ Credentials saved securely to .env (strictly excluded from git).[/bold green]")

    # Step 3: Database & Ready Check
    console.print("\n[bold green]Step 3: Database & Pipeline Verification[/bold green]")
    from .db import init_db
    db_path = init_db()
    console.print(f"✔ SQLite Ledger active at [cyan]{db_path}[/cyan]")

    # Setup summary table
    table = Table(title="Configuration Summary")
    table.add_column("Service / Tier", style="cyan")
    table.add_column("Status", style="white")

    updated_env = read_env_file()
    table.add_row("Tier 1: Direct APIs (Greenhouse/Lever/Ashby)", "[bold green]Active (Free, No Key Required)[/bold green]")
    table.add_row("Tier 2: JobSpy (LinkedIn/Indeed/Glassdoor)", "[bold green]Active (Free, No Key Required)[/bold green]")
    table.add_row("Tier 3: Apify Naukri Anti-Bot", "[green]Configured[/green]" if updated_env.get("APIFY_API_TOKEN") else "[dim]Disabled (Optional)[/dim]")
    table.add_row("Tier 4: Firecrawl Enterprise Portals", "[green]Configured[/green]" if updated_env.get("FIRECRAWL_API_KEY") else "[dim]Disabled (Optional)[/dim]")
    table.add_row("Notion Tabular Sync", "[green]Configured[/green]" if updated_env.get("NOTION_API_KEY") else "[dim]Disabled (Optional)[/dim]")
    table.add_row("LLM Resume Tailoring", "[green]Configured[/green]" if updated_env.get("GEMINI_API_KEY") else "[dim]Mock Mode (Default)[/dim]")
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
