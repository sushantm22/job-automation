from __future__ import annotations

from pathlib import Path
from typing import List

import typer
import yaml

from .config import load_settings
from .db import init_db, list_jobs, upsert_jobs
from .discovery import (
    CompanyRegistry,
    JobDiscoveryEngine,
    fetch_ashby_jobs,
    fetch_greenhouse_jobs,
    fetch_jobspy_jobs,
    fetch_lever_jobs,
    resolve_domain_to_ats,
)
from .llm.base import MockLLMClient
from .scoring import hard_filter_jobs, score_job
from .utils.net import use_system_trust_store

# Verify HTTPS with the OS trust store so certificate checks work in any terminal (e.g. VS Code/Copilot).
use_system_trust_store()

app = typer.Typer(add_completion=False, help="Job application automation assistant")


def _show_progress() -> None:
    """Print this project's progress lines (not third-party logs) for long commands, so a run that
    takes minutes visibly keeps moving instead of looking stuck."""
    import logging
    import sys

    log = logging.getLogger("src")
    if not any(getattr(h, "_progress", False) for h in log.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._progress = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


@app.command()
def init() -> None:
    """Create the SQLite database and basic schema."""
    db_path = init_db()
    typer.echo(f"Database initialized at {db_path}")
    seeded = CompanyRegistry().ensure_seeded()
    if seeded:
        typer.echo(f"Loaded {seeded} company boards from companies.yaml into the registry.")


@app.command()
def discover(
    tiers: str = typer.Option("all", help="Tiers to execute: 'all', or comma-separated numbers '1,2,3,4'"),
    results_per_board: int = typer.Option(
        0, help="Job-board results per site per role search (0 = discovery.jobspy.results_per_search in config.yaml)"
    ),
    company_limit: int = typer.Option(50, help="Max companies to query per run for Tier 1 (0 for all registered)"),
    auto_harvest: bool = typer.Option(True, help="Automatically harvest new company ATS slugs from incoming job URLs"),
) -> None:
    """
    Executes the 4-Tier Zero-Human-Intervention Job Discovery Engine:
      • Tier 1: Direct ATS APIs (Greenhouse / Lever / Ashby / SmartRecruiters)
      • Tier 2: JobSpy Aggregators (LinkedIn / Indeed / Glassdoor)
      • Tier 3: Apify Cloud Anti-Bot (Naukri & Protected Sites)
      • Tier 4: Firecrawl Enterprise Portals (Google / Apple / Uber / Netflix)
    Deduplicates all findings into SQLite ledger and auto-harvests new ATS boards.
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()
    settings = load_settings()
    if not settings.search_keywords:
        typer.echo(
            "No job titles are set yet, so there is nothing to search for.\n"
            "Set them with:  python -m src.cli onboard set-search --roles \"Sales Manager, Key Account Manager\"\n"
            "(or tell your AI assistant which job titles you want)."
        )
        raise typer.Exit(code=1)
    init_db()  # idempotent: a new user can run discover without running init first
    engine = JobDiscoveryEngine(settings=settings)

    # Parse requested tiers
    if tiers.strip().lower() == "all":
        selected_tiers = [1, 2, 3, 4]
    else:
        try:
            selected_tiers = [int(t.strip()) for t in tiers.split(",") if t.strip()]
        except ValueError:
            typer.echo(f"Invalid tiers format: '{tiers}'. Expected 'all' or '1,2,3,4'.")
            raise typer.Exit(code=1)

    _show_progress()
    console.print("\n[bold cyan]🚀 Starting Multi-Tier Job Discovery Engine[/bold cyan]")
    console.print(f"Active Tiers: [green]{selected_tiers}[/green] | Target: Pan-India & Remote\n")

    result = engine.execute_all_tiers(
        selected_tiers=selected_tiers,
        company_limit=company_limit if company_limit > 0 else None,
        results_per_board=results_per_board if results_per_board > 0 else None,
        auto_harvest=auto_harvest,
    )

    # Display Rich Breakdown Table
    table = Table(title="Discovery Run Summary (All Tiers)")
    table.add_column("Tier", style="cyan")
    table.add_column("Channel / Platform", style="white")
    table.add_column("Jobs Found", style="green", justify="right")

    tier_map = {
        "tier1_direct_apis": ("Tier 1", "Direct APIs (Greenhouse / Lever / Ashby / SmartRecruiters)"),
        "tier1_jobhive": ("Tier 1", f"JobHive dataset ({len(settings.jobhive_platforms or [])} ATS sources: Workday / Oracle / SuccessFactors / Phenom / ...)"),
        "tier2_jobspy": ("Tier 2", "JobSpy (LinkedIn / Indeed / Glassdoor / Naukri)"),
        "tier3_apify": ("Tier 3", "Apify (Naukri & Protected Aggregators)"),
        "tier4_firecrawl": ("Tier 4", "Firecrawl (Google / Apple / Enterprise Portals)"),
    }

    for key, (t_label, desc) in tier_map.items():
        table.add_row(t_label, desc, str(result["tier_counts"].get(key, 0)))

    table.add_section()
    table.add_row("[bold]Total Discovered[/bold]", "Across All Tiers", f"[bold]{result['total_discovered']}[/bold]")
    table.add_row("[bold green]Net New Stored[/bold green]", "Inserted into SQLite Deduplication Ledger", f"[bold green]{result['net_new_inserted']}[/bold green]")
    table.add_row("[dim]Duplicates Prevented[/dim]", "Already tracked in SQLite", f"[dim]{result['duplicates_prevented']}[/dim]")
    table.add_row("[bold magenta]Notion Synced[/bold magenta]", "Live Opportunities in Notion Table", f"[bold magenta]{result.get('notion_synced', 0)}[/bold magenta]")
    console.print(table)

    if result.get("network_unavailable"):
        console.print(
            "\n[bold red]❌ No internet access:[/bold red] none of the job sources could be reached, so nothing "
            "was searched. Check your connection (AI tools that sandbox commands: allow network access) and run "
            "discover again."
        )
        raise typer.Exit(code=1)

    if result.get("total_discovered", 0) > 0:
        from .onboard_steps import mark_step
        mark_step("first_discovery")

    if result.get("registry_seeded", 0) > 0:
        console.print(f"🌱 [bold green]First run:[/bold green] loaded {result['registry_seeded']} company boards from companies.yaml into your registry.")

    window = result.get("jobspy_window_hours") or {}
    if window:
        from .discovery.engine import _describe_hours

        line = f"🔎 [bold]Job boards:[/bold] searched jobs posted in the last {_describe_hours(window.get('others'))}"
        if window.get("linkedin") != window.get("others"):
            line += f" (LinkedIn: {_describe_hours(window.get('linkedin'))})"
        console.print(line + ". Later runs only look back to the previous run.")

    too_old_matching = result.get("too_old_matching", 0)
    baseline_matching = result.get("baseline_matching", 0)
    if too_old_matching or baseline_matching:
        parts = []
        if too_old_matching:
            parts.append(
                f"skipped {too_old_matching} matching jobs past the age limit ({settings.max_job_age_days} days "
                f"for job boards, {settings.max_company_job_age_days} for company career sites)"
            )
        if baseline_matching:
            pretty = {"workday": "Workday", "successfactors": "SuccessFactors"}
            names = sorted({pretty.get(src.split(":")[-1], src.split(":")[-1].title())
                            for src in (result.get("baseline_matching_by_source") or {})})
            parts.append(
                f"held back {baseline_matching} matching {'/'.join(names)} jobs that have no posting date "
                "(this first read is the starting point; jobs that newly appear there are added from the next daily update)"
            )
        console.print("🧹 [bold]Freshness:[/bold] " + "; ".join(parts) + ".")

    related = result.get("related_titles") or []
    if related:
        from rich.markup import escape

        shown = escape(", ".join(f"{title} ({count})" for title, count in related))  # titles may contain "[...]"
        console.print(
            f"💡 [bold]Close titles found[/bold] that aren't in your roles yet: {shown}.\n"
            "   To include some, save your roles plus the ones you want: "
            "[bold cyan]python -m src.cli onboard set-search --roles \"<current roles>, <new titles>\"[/bold cyan]"
        )
    if result.get("stale_closed", 0):
        console.print(f"🗓  [bold]{result['stale_closed']} stored jobs[/bold] passed the age limit and were marked closed.")

    if result.get("jobs_closed", 0) or result.get("jobs_reopened", 0):
        console.print(
            f"🔒 [bold]Closed-job tracking:[/bold] {result.get('jobs_closed', 0)} jobs no longer listed were marked "
            f"closed, {result.get('jobs_reopened', 0)} reappeared and were reopened."
        )

    if result.get("harvested_companies", 0) > 0:
        console.print(f"🌱 [bold green]Auto-Harvested:[/bold green] {result['harvested_companies']} new verified company ATS boards into registry!")

    if result.get("notion_synced", 0) > 0:
        console.print(f"📋 [bold cyan]Notion Table Updated:[/bold cyan] {result['notion_synced']} jobs synced to [link=https://app.notion.com/p/{settings.notion_database_id}]Notion Table[/link]")
    if result.get("notion_pending", 0) > 0:
        console.print(
            f"⏳ [bold yellow]{result['notion_pending']} more jobs are waiting for Notion[/bold yellow] "
            f"(this run synced up to {settings.notion_max_sync_per_run}). Push them all with: "
            "[bold cyan]python -m src.cli sync-notion[/bold cyan]"
        )
    elif result.get("notion_synced", 0) == 0 and settings.notion_enabled and settings.notion_database_id:
        console.print(f"📋 [dim]Notion Database:[/dim] All stored jobs are up to date in [link=https://app.notion.com/p/{settings.notion_database_id}]Notion[/link]")


@app.command("seed-companies")
def seed_companies(
    seed_file: Path = typer.Option(
        Path(__file__).resolve().parent.parent / "data" / "seeds" / "companies_seed.json",
        help="Path to seed JSON file",
    ),
    sync_yaml: bool = typer.Option(True, help="Sync to src/discovery/companies.yaml"),
) -> None:
    """Import 1,000+ verified tech company slugs into the database registry and sync to companies.yaml."""
    registry = CompanyRegistry()
    inserted = registry.import_from_seed(seed_file)
    typer.echo(f"Successfully imported {inserted} new companies from {seed_file.name}.")

    if sync_yaml:
        total_synced = registry.sync_to_yaml()
        typer.echo(f"Synced {total_synced} active companies to src/discovery/companies.yaml.")

    stats = registry.get_stats()
    typer.echo(f"Current Registry Stats: {stats['total_companies']} total companies tracked.")


@app.command("explore-companies")
def explore_companies(
    target_file: Path = typer.Option(
        Path(__file__).resolve().parent.parent / "data" / "target_company_sites.json",
        help="Path to company domains JSON file",
    ),
    domain: str = typer.Option(None, help="Single company domain or URL to probe"),
) -> None:
    """Probes company websites/domains to detect their ATS (Greenhouse, Lever, Ashby) and auto-registers them."""
    registry = CompanyRegistry()
    targets: list[str] = []

    if domain:
        targets = [domain]
    elif target_file.exists():
        import json
        with target_file.open("r", encoding="utf-8") as handle:
            targets = json.load(handle)

    typer.echo(f"Exploring ATS boards across {len(targets)} target companies...")
    found_count = 0

    for site in targets:
        try:
            discovered_slugs = resolve_domain_to_ats(site, timeout=6.0, verify_live=True)
            for item in discovered_slugs:
                platform = item["platform"]
                slug = item["slug"]
                job_cnt = item.get("job_count", 0)
                typer.echo(f"  [Found & Verified] {site} -> {platform.upper()}: {slug} (active jobs: {job_cnt})")
                from .db import upsert_company
                is_new = upsert_company(
                    platform=platform,
                    slug=slug,
                    name=item.get("name"),
                    status="active",
                    job_count=job_cnt,
                    discovered_via="domain_probe",
                )
                if is_new:
                    found_count += 1
        except Exception as err:
            typer.echo(f"  [Error] {site}: {err}")

    if found_count > 0:
        registry.sync_to_yaml()
        typer.echo(f"✨ Successfully discovered and registered {found_count} new company boards!")
    else:
        typer.echo("Done exploring. No new unmapped ATS boards found in this batch.")


@app.command("validate-companies")
def validate_companies(
    platform: str = typer.Option(None, help="Platform to validate: 'greenhouse', 'lever', 'ashby'"),
    batch_size: int = typer.Option(50, help="Number of companies to check"),
    prune_inactive: bool = typer.Option(True, help="Mark genuinely 404/defunct boards as inactive"),
) -> None:
    """Probes registered companies to verify they are still active, pruning only explicit 404 defunct boards."""
    from .discovery.harvester import probe_company_board
    from .db import list_companies, upsert_company

    registry = CompanyRegistry()
    rows = list_companies(platform=platform, status="active", limit=batch_size)
    typer.echo(f"Validating {len(rows)} registered company boards...")

    active_count = 0
    inactive_count = 0
    network_skipped = 0

    for r in rows:
        p = r["platform"]
        slug = r["slug"]
        probe = probe_company_board(p, slug, timeout=5.0)

        if probe["valid"]:
            active_count += 1
            upsert_company(
                platform=p,
                slug=slug,
                name=probe.get("name"),
                status="active",
                job_count=probe.get("job_count", 0),
            )
            typer.echo(f"  ✅ [Active] {p.upper()}: {slug} (jobs: {probe.get('job_count', 0)})")
        elif probe["status"] == "not_found":
            # Genuine 404: The board slug was deleted or moved off this ATS
            inactive_count += 1
            typer.echo(f"  ⚠️  [Defunct/404] {p.upper()}: {slug} ({probe.get('error', 'HTTP 404')})")
            if prune_inactive:
                upsert_company(platform=p, slug=slug, status="inactive")
        else:
            # Network failure, DNS issue, or rate limit: KEEP ACTIVE, DO NOT PRUNE!
            network_skipped += 1
            typer.echo(f"  ℹ️  [Retained - {probe['status']}] {p.upper()}: {slug} ({probe.get('error')})")

    if inactive_count > 0 and prune_inactive:
        registry.sync_to_yaml()
        typer.echo(f"Pruned {inactive_count} genuinely defunct boards from companies.yaml.")

    typer.echo(f"\nValidation complete:")
    typer.echo(f"  • {active_count} verified active boards")
    typer.echo(f"  • {inactive_count} defunct 404 boards (pruned)")
    typer.echo(f"  • {network_skipped} network/DNS skipped (safely retained as active)")


@app.command("companies-stats")
def companies_stats() -> None:
    """Display statistics about tracked companies in the registry."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    registry = CompanyRegistry()
    stats = registry.get_stats()

    table = Table(title="Company ATS Registry Statistics")
    table.add_column("Platform", style="cyan")
    table.add_column("Company Count", style="green", justify="right")
    table.add_column("Open Jobs Known", style="yellow", justify="right")

    total_jobs = sum(d["jobs"] for d in stats["by_platform"].values())
    for platform, data in stats["by_platform"].items():
        table.add_row(platform.title(), str(data["count"]), str(data["jobs"]))

    table.add_section()
    table.add_row("Total Active", str(stats.get("active_companies", 0)), str(total_jobs))
    console.print(table)
    inactive_count = stats.get("by_status", {}).get("inactive", 0)
    if inactive_count:
        console.print(f"[dim]Pruned / Inactive: {inactive_count} boards (excluded from crawling)[/dim]")
    console.print(f"[bold]Discovered via:[/bold] {stats['by_source']}")


@app.command()
def score() -> None:
    """Score all new jobs and update their match result in the database."""
    settings = load_settings()
    rows = list_jobs(status="new")
    llm = MockLLMClient()
    for row in rows:
        job_data = {
            "title": row["title"],
            "location": row["location"],
            "description": row["description"],
            "source": row["source"],
            "company": row["company"],
        }
        result = score_job(job_data, profile_summary={"skills": ["python", "backend"], "experience": ["software engineering"]}, llm=llm)
        typer.echo(f"{row['title']} -> {result.score}/100 ({result.reason})")


@app.command()
def list() -> None:
    """List jobs currently stored in the database."""
    rows = list_jobs()
    if not rows:
        typer.echo("No jobs found.")
        return
    for row in rows:
        typer.echo(f"[{row['status']}] {row['company']} - {row['title']} ({row['location']})")


@app.command("init-notion-db")
def init_notion_db(
    parent_page_id: str = typer.Option(..., help="Notion Parent Page URL or 32-character Page ID"),
    title: str = typer.Option("Automated Job Applications", help="Title of the Notion database table"),
) -> None:
    """Creates a structured tabular Jobs Database inside a Notion page using the Notion API."""
    from .integrations.notion_client import create_notion_job_database, clean_notion_id

    typer.echo(f"Creating Notion Database under page: {parent_page_id}...")
    try:
        res = create_notion_job_database(parent_page_id=parent_page_id, title=title)
        db_id = res["id"]
        db_url = res.get("url")
        typer.echo(f"✅ Successfully created Notion Database table!")
        typer.echo(f"  • Title: {title}")
        typer.echo(f"  • Database ID: {db_id}")
        typer.echo(f"  • Table URL: {db_url}")
        from .onboarding import write_env_file
        write_env_file({
            "NOTION_DATABASE_ID": clean_notion_id(db_id),
            "NOTION_PARENT_PAGE_ID": clean_notion_id(parent_page_id),
        })
        typer.echo("✅ Saved NOTION_DATABASE_ID and NOTION_PARENT_PAGE_ID to .env — discovery will sync here automatically.")
    except Exception as err:
        from .integrations.notion_client import explain_notion_error
        from .onboarding import NOTION_CONNECT_TIP
        message, sharing_problem = explain_notion_error(err)
        typer.echo(f"❌ Error creating Notion database: {message}")
        if sharing_problem:
            typer.echo(NOTION_CONNECT_TIP)
        raise typer.Exit(code=1)


@app.command("prune-old")
def prune_old(
    max_age_days: int = typer.Option(None, help="Override search.max_job_age_days (job boards) for this run"),
) -> None:
    """Close stored jobs past the age limit (and old undated backlog); update their Notion rows."""
    from . import db as db_module
    from .integrations.notion_client import sync_closed_status

    settings = load_settings()
    days = max_age_days if max_age_days is not None else settings.max_job_age_days
    db_path = db_module.DB_PATH
    db_module.init_db(db_path)
    company_days = settings.max_company_job_age_days
    closed = db_module.close_stale_jobs(
        days, db_path=db_path, first_seen=settings.undated_jobs == "first_seen", company_max_days=company_days
    )
    typer.echo(
        f"Marked {closed} jobs past the age limit ({days} days for job boards, {company_days} for company "
        "career sites, or old undated backlog) as closed."
    )
    if settings.notion_enabled and settings.notion_database_id:
        res = sync_closed_status(db_path=db_path)
        typer.echo(
            f"Notion: {res['closed']} rows set to Closed, {res['left_alone']} left alone "
            f"(you had moved them past Reviewing), {res['failed']} failed."
        )


@app.command("sync-notion")
def sync_notion(
    limit: int = typer.Option(0, help="Max unsynced jobs to push (0 = all pending)"),
    database_id: str = typer.Option(None, help="Target Notion Database ID (defaults to config)"),
) -> None:
    """Syncs new jobs from SQLite database to the Notion Database table."""
    from .integrations.notion_client import sync_jobs_to_notion

    _show_progress()
    typer.echo("Syncing jobs from SQLite to Notion...")
    try:
        res = sync_jobs_to_notion(database_id=database_id, limit=limit if limit > 0 else None)
        from .integrations.notion_client import sync_closed_status
        closed = sync_closed_status()
        typer.echo(f"Sync complete:")
        typer.echo(f"  • {res['synced']} jobs synced to Notion")
        if closed["closed"] or closed["reopened"]:
            typer.echo(f"  • {closed['closed']} rows marked Closed, {closed['reopened']} reopened")
        if res.get("failed", 0) > 0:
            typer.echo(f"  • {res['failed']} jobs failed")
    except Exception as err:
        typer.echo(f"❌ Error during Notion sync: {err}")


@app.command("setup")
def setup() -> None:
    """Guided Onboarding Agent: configures roles, locations, credentials, and local database."""
    from .onboarding import run_interactive_onboarding
    run_interactive_onboarding()


@app.command("reset-db")
def reset_db_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Clears all jobs and applications from the local database while preserving schema."""
    from rich.prompt import Confirm
    from rich.console import Console
    from .db import reset_db

    console = Console()
    if not yes:
        proceed = Confirm.ask(
            "[bold red]⚠️ Are you sure you want to delete all jobs and reset your local database?[/bold red]",
            default=False,
        )
        if not proceed:
            console.print("[dim]Operation cancelled.[/dim]")
            return

    res = reset_db()
    console.print(f"[bold green]✔ Local database reset cleanly:[/bold green] Deleted {res['jobs_deleted']} jobs and {res['applications_deleted']} applications.")


@app.command("verify-secrets")
def verify_secrets_cmd() -> None:
    """Scans all git-tracked files to ensure no API tokens or secrets are exposed."""
    from rich.console import Console
    from rich.table import Table
    from .onboarding import audit_tracked_secrets

    console = Console()
    violations = audit_tracked_secrets()
    if violations:
        console.print("\n[bold red]❌ SECURITY ALERT: Potential API Keys / Secrets Exposed in Git Tracked Files![/bold red]")
        table = Table(title="Exposed Credentials")
        table.add_column("File", style="cyan")
        table.add_column("Secret Type", style="yellow")
        table.add_column("Masked Snippet", style="white")
        for v in violations:
            table.add_row(v["file"], v["type"], v["snippet"])
        console.print(table)
        console.print("\n[red]Action Required:[/red] Remove these tokens from the files above and move them to `.env` before pushing to GitHub.")
        raise typer.Exit(code=1)
    else:
        console.print("[bold green]✔ Security Audit Passed:[/bold green] Zero API keys or secrets detected in git-tracked files.")


onboard_app = typer.Typer(
    add_completion=False,
    help="Non-interactive onboarding steps. Built for AI assistants: each command takes its answers as "
    "arguments and never prompts. See docs/ONBOARDING_PLAYBOOK.md.",
)
app.add_typer(onboard_app, name="onboard")


def _emit(data: dict, as_json: bool, human: str) -> None:
    import json as _json
    typer.echo(_json.dumps(data, indent=2) if as_json else human)


@onboard_app.command("prepare")
def onboard_prepare(as_json: bool = typer.Option(False, "--json")) -> None:
    """Step 0: create .env from .env.example, the database, and the company registry. Safe to re-run."""
    from .onboard_steps import prepare

    res = prepare()
    lines = [
        f".env: {'created from .env.example' if res['env_created'] else 'already exists'} ({res['env_file']})",
        f"Database: {res['database']}",
        f"Company boards: {res['registry_boards']}" + (f" (loaded {res['registry_seeded']} from companies.yaml)" if res["registry_seeded"] else ""),
    ]
    _emit(res, as_json, "\n".join(lines))


@onboard_app.command("check-keys")
def onboard_check_keys(as_json: bool = typer.Option(False, "--json")) -> None:
    """Check the keys in .env online without printing them (use after the user edits .env themselves)."""
    from .onboard_steps import check_keys

    res = check_keys()
    _emit(res, as_json, "\n".join(f"{name}: {state}" for name, state in res.items()))


@onboard_app.command("status")
def onboard_status(as_json: bool = typer.Option(False, "--json", help="Machine-readable output")) -> None:
    """Show what is set up, what is missing, and the next step."""
    from .onboard_steps import STEP_ORDER, get_status

    status = get_status()
    lines = [f"Database: {status['database']}  |  Company boards: {status['registry_boards']}"]
    for step_id in STEP_ORDER:
        info = status["steps"][step_id]
        mark = "✔" if info["done"] else "✗"
        extra = " (skipped)" if info.get("skipped") else (" (optional)" if info.get("optional") and not info["done"] else "")
        lines.append(f"  {mark} {step_id}{extra}")
    lines.append("Onboarding complete." if status["complete"] else f"Next step: {status['next_step']}")
    _emit(status, as_json, "\n".join(lines))


@onboard_app.command("set-search")
def onboard_set_search(
    roles: str = typer.Option(None, help="Comma-separated job titles, e.g. 'Sales Manager, Key Account Manager'"),
    locations: str = typer.Option(None, help="Comma-separated locations, e.g. 'India, Remote, Pune'"),
    exclude: str = typer.Option(None, help="Comma-separated words that reject a job, e.g. 'intern, unpaid'"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Save target roles/locations to config.local.yaml (gitignored). Roles are required the first time; later, omit all options to keep what is saved."""
    from .onboard_steps import set_search

    try:
        res = set_search(roles=roles, locations=locations, exclude=exclude)
    except ValueError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1)
    _emit(res, as_json, f"Search saved.\n  Roles: {', '.join(res['roles'])}\n  Locations: {', '.join(res['locations'])}\n  Exclude: {', '.join(res['exclude'])}")


@onboard_app.command("set-profile")
def onboard_set_profile(
    fields: List[str] = typer.Argument(..., help="field=value pairs, e.g. first_name=Asha city=Pune resume=~/cv.pdf"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Fill data/profile.json (gitignored). A resume path outside the project is copied into data/."""
    from .onboard_steps import PROFILE_FIELDS, set_profile

    updates: dict[str, str] = {}
    for item in fields:
        if "=" not in item:
            typer.echo(f"Error: '{item}' is not field=value. Fields: {', '.join(PROFILE_FIELDS)}", err=True)
            raise typer.Exit(code=1)
        key, value = item.split("=", 1)
        updates[key.strip()] = value
    try:
        res = set_profile(updates)
    except ValueError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1)
    human = "Profile saved." + (f"\n  Still missing: {', '.join(res['missing'])}" if res["missing"] else "\n  Basic profile complete.")
    _emit(res, as_json, human)


@onboard_app.command("set-key")
def onboard_set_key(
    name: str = typer.Argument(..., help="NOTION_API_KEY | APIFY_API_TOKEN | FIRECRAWL_API_KEY | GEMINI_API_KEY"),
    verify: bool = typer.Option(True, help="Check the key online where possible"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Save a secret to .env. The value is read from stdin so it never appears in the command line."""
    import sys
    from .onboard_steps import set_key

    if sys.stdin.isatty():  # nothing piped in: reading would wait for keyboard input forever
        typer.echo(
            f"Error: no value piped in. Pipe the key, e.g. printf '%s' \"$KEY\" | ... onboard set-key {name}, "
            "or let the user add it to .env themselves and run 'onboard check-keys'.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        res = set_key(name.strip().upper(), sys.stdin.read(), verify=verify)
    except ValueError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1)
    check = {
        "verified": "verified online",
        "failed": "saved, but the online check FAILED (wrong or expired key?)",
        "set (no online check)": "saved (no online check for this key)",
        "not checked": "saved (not checked)",
    }.get(res["check"], f"saved, but {res['check']}")
    _emit(res, as_json, f"{res['saved']}: {check}")


@onboard_app.command("skip")
def onboard_skip(step: str = typer.Argument(..., help="api_keys | notion | profile")) -> None:
    """Mark an optional step as skipped so status moves on."""
    from .onboard_steps import skip_step

    try:
        skip_step(step)
    except ValueError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Skipped '{step}'. You can come back to it any time.")


if __name__ == "__main__":
    app()
