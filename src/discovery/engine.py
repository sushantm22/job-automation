from __future__ import annotations

import logging
from typing import Any
from urllib.error import HTTPError

from ..config import Settings, load_settings
from ..db import (
    DB_PATH,
    admit_first_seen,
    close_missing_jobs,
    close_stale_jobs,
    get_connection,
    mark_company_checked,
    reopen_jobs,
    upsert_jobs,
)
from .freshness import first_seen_scope, is_too_old, uses_first_seen
from ..utils.net import never_reached_server
from .apify_adapter import fetch_apify_naukri_jobs
from .ashby import fetch_ashby_jobs
from .base import JobRecord
from .firecrawl_adapter import fetch_firecrawl_portal_jobs
from .greenhouse import fetch_greenhouse_jobs
from .jobhive import fetch_jobhive_jobs
from .jobspy_adapter import fetch_jobspy_jobs
from .lever import fetch_lever_jobs
from .registry import CompanyRegistry
from .smartrecruiters import fetch_smartrecruiters_jobs
from .ats_scrapers_adapter import LIVE_PLATFORMS, fetch_live_ats_jobs

logger = logging.getLogger(__name__)
PROGRESS_EVERY = 25  # boards between progress lines, so long runs never look stuck


def _count_unsynced(db_path) -> int:
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT count(*) FROM jobs WHERE notion_page_id IS NULL AND closed_at IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()


class JobDiscoveryEngine:
    """
    Centralized 4-Tier Zero-Human-Intervention Job Discovery Engine.

    Tier 1: Direct ATS APIs (Greenhouse / Lever / Ashby / SmartRecruiters)
    Tier 2: JobSpy Aggregators (LinkedIn / Indeed / Glassdoor)
    Tier 3: Apify Cloud Anti-Bot (Naukri & Protected Aggregators)
    Tier 4: Firecrawl Enterprise Portals (Google / Apple / Uber / Netflix)
    """

    def __init__(self, settings: Settings | None = None, db_path=DB_PATH):
        self.settings = settings or load_settings()
        self.db_path = db_path
        self.registry = CompanyRegistry(db_path=self.db_path)
        self.registry_seeded = 0
        self.network_unavailable = False
        self.jobhive_snapshots: dict[str, dict[str, Any]] = {}

    def run_tier1_direct_apis(self, company_limit: int | None = 50) -> list[JobRecord]:
        """
        Tier 1: High-speed, 100% free direct API polling for tracked ATS boards
        (Greenhouse, Lever, Ashby, SmartRecruiters, and live Keka/SuccessFactors via ats-scrapers).
        Polls the least-recently-checked boards first so `company_limit` rotates through the registry.
        """
        self.registry_seeded = self.registry.ensure_seeded()
        slugs_by_platform = self.registry.get_slugs_by_platform(limit=company_limit, stale_first=True)
        discovered: list[JobRecord] = []
        polled = offline_failures = done = 0
        total = sum(len(s) for s in slugs_by_platform.values())
        logger.info(f"[Tier 1] Checking {total} company job boards...")

        for platform, slugs in slugs_by_platform.items():
            for slug in slugs:
                done += 1
                if done % PROGRESS_EVERY == 0:
                    logger.info(f"[Tier 1] {done}/{total} boards checked, {len(discovered)} jobs so far...")
                try:
                    if platform == "greenhouse":
                        jobs = fetch_greenhouse_jobs(slug)
                    elif platform == "lever":
                        jobs = fetch_lever_jobs(slug)
                    elif platform == "ashby":
                        jobs = fetch_ashby_jobs(slug)
                    elif platform == "smartrecruiters":
                        jobs = fetch_smartrecruiters_jobs(slug)
                    elif platform in LIVE_PLATFORMS:
                        jobs = fetch_live_ats_jobs(platform, slug)
                    else:
                        continue

                    polled += 1
                    discovered.extend(jobs)
                    mark_company_checked(platform, slug, job_count=len(jobs), db_path=self.db_path)
                except HTTPError as err:
                    polled += 1  # the server answered, so the network works
                    if err.code == 404:
                        # The board is gone (company left this ATS). Same rule as `validate-companies`:
                        # only an explicit 404 deactivates; network errors and rate limits never do.
                        logger.warning(f"[Tier 1: {platform}] Board '{slug}' no longer exists (404); removed from your registry.")
                        mark_company_checked(platform, slug, db_path=self.db_path, status="inactive")
                    else:
                        logger.warning(f"[Tier 1: {platform}] Error polling {slug}: {err}")
                        mark_company_checked(platform, slug, db_path=self.db_path)
                except Exception as err:
                    polled += 1
                    if never_reached_server(err):
                        # Nothing was checked (offline / sandboxed), so don't stamp: the board keeps its
                        # place in the rotation instead of being skipped next run unsearched.
                        offline_failures += 1
                        continue
                    logger.warning(f"[Tier 1: {platform}] Error polling {slug}: {err}")
                    # Still stamp the check so a failing board doesn't stay at the front of the rotation.
                    mark_company_checked(platform, slug, db_path=self.db_path)

        self.network_unavailable = polled > 0 and offline_failures == polled
        if offline_failures:
            logger.warning(
                f"[Tier 1] {offline_failures}/{polled} boards could not be reached (no internet access?)."
            )
        logger.info(f"[Tier 1: Direct APIs] Total fetched: {len(discovered)} jobs")
        return discovered

    def run_tier1_jobhive(self) -> list[JobRecord]:
        """Tier 1 (dataset): India jobs from the public JobHive dataset (Workday, Oracle, ...)."""
        import hashlib
        import json
        from pathlib import Path

        s = self.settings
        # Cache stamps are only valid for the same search settings and database.
        cache_key = hashlib.sha1(json.dumps(
            [s.search_keywords, s.locations, s.exclude_keywords, str(self.db_path)], sort_keys=True
        ).encode()).hexdigest()
        logger.info("[Tier 1: JobHive] Reading the daily dataset (Workday, Oracle, SuccessFactors, ...)...")
        try:
            jobs = fetch_jobhive_jobs(
                platforms=s.jobhive_platforms,
                cache_path=Path(f"{self.db_path}.jobhive-cache.json"),
                cache_key=cache_key,
                snapshots=self.jobhive_snapshots,
            )
        except Exception as err:  # e.g. pyarrow missing: never break discovery
            logger.warning(f"[Tier 1: JobHive] Skipped: {err}")
            return []
        logger.info(f"[Tier 1: JobHive] Total fetched: {len(jobs)} India jobs")
        return jobs

    def run_tier2_jobspy(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        results_wanted: int = 15,
    ) -> list[JobRecord]:
        """Tier 2: Multi-aggregator scraping (LinkedIn, Indeed, Glassdoor) for India & Remote."""
        kw = keywords or self.settings.search_keywords
        loc = locations or self.settings.locations
        try:
            jobs = fetch_jobspy_jobs(
                keywords=kw,
                locations=loc,
                results_wanted=results_wanted,
                include_remote=True,
            )
            logger.info(f"[Tier 2: JobSpy] Total fetched: {len(jobs)} jobs")
            return jobs
        except Exception as err:
            logger.warning(f"[Tier 2: JobSpy] Error executing JobSpy: {err}")
            return []

    def run_tier3_apify(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_jobs: int = 25,
    ) -> list[JobRecord]:
        """Tier 3: Cloud anti-bot actor for Naukri and protected sites."""
        kw = keywords or self.settings.search_keywords
        loc = locations or self.settings.locations
        token = self.settings.apify_api_token
        actor_id = self.settings.apify_actor_id

        return fetch_apify_naukri_jobs(
            keywords=kw,
            locations=loc,
            api_token=token,
            actor_id=actor_id,
            max_jobs=max_jobs,
        )

    def run_tier4_firecrawl(
        self,
        portals: list[dict[str, str]] | None = None,
        covered_companies: set[str] | None = None,
    ) -> list[JobRecord]:
        """Tier 4: Smart fallback — only scrapes enterprise portals not already covered by Tiers 1-2."""
        target_portals = portals or self.settings.enterprise_portals or None
        api_key = self.settings.firecrawl_api_key
        budget = getattr(self.settings, "firecrawl_daily_budget", 10)

        return fetch_firecrawl_portal_jobs(
            portals=target_portals,
            api_key=api_key,
            budget=budget,
            covered_companies=covered_companies,
            roles=self.settings.search_keywords,
        )

    def _apply_freshness(self, jobs: list[JobRecord]) -> tuple[list[JobRecord], int, int]:
        """Returns (jobs to keep, skipped as too old, skipped as first-seen baseline)."""
        max_age = self.settings.max_job_age_days
        fresh = [j for j in jobs if not is_too_old(j.posted_at, max_age)]
        too_old = len(jobs) - len(fresh)
        if self.settings.undated_jobs != "first_seen":
            return fresh, too_old, 0

        by_scope: dict[str, set[str]] = {}
        for j in fresh:
            if not j.posted_at and j.url and uses_first_seen(j.source):
                by_scope.setdefault(first_seen_scope(j.source, j.company), set()).add(j.url)
        admitted = admit_first_seen(by_scope, db_path=self.db_path) if by_scope else set()
        kept = [j for j in fresh if j.posted_at or not uses_first_seen(j.source) or j.url in admitted]
        return kept, too_old, len(fresh) - len(kept)

    def execute_all_tiers(
        self,
        selected_tiers: list[int] | None = None,
        company_limit: int | None = 50,
        results_per_board: int = 15,
        auto_harvest: bool = True,
        apply_hard_filter: bool = True,
    ) -> dict[str, Any]:
        """
        Executes all selected tiers, feeds discovered ATS links back into the Tier 1 registry,
        and saves deduplicated postings to the SQLite ledger.
        """
        if apply_hard_filter and not self.settings.search_keywords:
            # With no roles the filter keeps everything, which would flood the database with
            # ~100k JobHive rows. Roles are per user and set during onboarding.
            raise ValueError(
                'No job titles are set. Run: python -m src.cli onboard set-search --roles "Sales Manager, ..."'
            )
        active_tiers = set(selected_tiers or [1, 2, 3, 4])
        self.jobhive_snapshots = {}
        all_jobs: list[JobRecord] = []
        tier_counts: dict[str, int] = {
            "tier1_direct_apis": 0,
            "tier1_jobhive": 0,
            "tier2_jobspy": 0,
            "tier3_apify": 0,
            "tier4_firecrawl": 0,
        }

        # 1. Tier 1: Direct APIs
        if 1 in active_tiers and self.settings.tier1_direct_apis:
            t1_jobs = self.run_tier1_direct_apis(company_limit=company_limit)
            tier_counts["tier1_direct_apis"] = len(t1_jobs)
            all_jobs.extend(t1_jobs)

        if 1 in active_tiers and self.settings.jobhive_enabled:
            hive_jobs = self.run_tier1_jobhive()
            tier_counts["tier1_jobhive"] = len(hive_jobs)
            all_jobs.extend(hive_jobs)

        # 2. Tier 2: JobSpy Aggregators
        if 2 in active_tiers and self.settings.tier2_jobspy:
            t2_jobs = self.run_tier2_jobspy(results_wanted=results_per_board)
            tier_counts["tier2_jobspy"] = len(t2_jobs)
            all_jobs.extend(t2_jobs)

        # 3. Tier 3: Apify — SMART FALLBACK for Naukri
        #    Only fires if JobSpy returned 0 results from Naukri
        if 3 in active_tiers and self.settings.tier3_apify:
            naukri_from_jobspy = sum(
                1 for j in all_jobs if j.source and "naukri" in j.source.lower()
            )
            if naukri_from_jobspy > 0:
                logger.info(
                    f"[Tier 3: Apify] Skipped — JobSpy already returned {naukri_from_jobspy} "
                    f"Naukri results. Apify fallback not needed."
                )
            else:
                logger.info(
                    "[Tier 3: Apify] JobSpy returned 0 Naukri results. "
                    "Activating Apify cloud anti-bot fallback."
                )
                t3_jobs = self.run_tier3_apify(max_jobs=results_per_board * 2)
                tier_counts["tier3_apify"] = len(t3_jobs)
                all_jobs.extend(t3_jobs)

        # 4. Tier 4: Firecrawl — SMART FALLBACK for enterprise portals
        #    Only scrapes portals for companies NOT already found in Tiers 1-2
        if 4 in active_tiers and self.settings.tier4_firecrawl:
            covered = {j.company.lower() for j in all_jobs if j.company}
            t4_jobs = self.run_tier4_firecrawl(covered_companies=covered)
            tier_counts["tier4_firecrawl"] = len(t4_jobs)
            all_jobs.extend(t4_jobs)

        # 5. Automated Feedback Loop (Auto-Harvesting)
        harvested_count = 0
        if auto_harvest:
            # Collect URLs from all jobs discovered in aggregator tiers (Tiers 2, 3, 4)
            aggregator_urls = [
                j.url for j in all_jobs if not j.source.startswith(("greenhouse", "lever", "ashby"))
            ]
            if aggregator_urls:
                harvested_count = self.registry.harvest_from_urls(aggregator_urls)

        # 6. Freshness: drop jobs past the age limit; undated bulk listings only when newly seen.
        fresh_jobs, too_old_skipped, baseline_skipped = self._apply_freshness(all_jobs)

        # 7. Deduplication & Persistence in SQLite
        raw_dicts = [
            {
                "source": j.source,
                "company": j.company,
                "title": j.title,
                "location": j.location,
                "url": j.url,
                "description": j.description,
                "posted_at": str(j.posted_at) if j.posted_at else None,
            }
            for j in fresh_jobs
            if j.url
        ]

        if apply_hard_filter and raw_dicts:
            from ..scoring import hard_filter_jobs
            target_dicts = hard_filter_jobs(
                raw_dicts,
                keywords=self.settings.search_keywords,
                locations=self.settings.locations,
                exclude=self.settings.exclude_keywords,
            )
        else:
            target_dicts = raw_dicts

        # Count existing before insertion to calculate true duplicates prevented
        conn = get_connection(self.db_path)
        try:
            count_before = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
        finally:
            conn.close()

        inserted_or_updated = upsert_jobs(target_dicts, db_path=self.db_path)

        conn = get_connection(self.db_path)
        try:
            count_after = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
        finally:
            conn.close()

        net_new = max(0, count_after - count_before)
        duplicates_prevented = len(target_dicts) - net_new

        # Closed-job tracking (JobHive platforms, e.g. Workday). Anything seen this run, by any
        # source, is open; jobs missing from a complete daily snapshot are marked closed.
        seen_urls = {j.url for j in all_jobs if j.url}
        jobs_reopened = reopen_jobs(seen_urls, db_path=self.db_path)
        jobs_closed = 0
        for platform, snap in self.jobhive_snapshots.items():
            if snap.get("closable"):
                jobs_closed += close_missing_jobs(
                    f"jobhive:{platform}", snap["urls"] | seen_urls, db_path=self.db_path
                )
        if jobs_closed or jobs_reopened:
            logger.info(f"[Closed jobs] {jobs_closed} marked closed, {jobs_reopened} reopened.")
        stale_closed = close_stale_jobs(
            self.settings.max_job_age_days, db_path=self.db_path,
            first_seen=self.settings.undated_jobs == "first_seen",
        )

        # 7. Optional Automatic Notion Database Sync
        notion_synced = 0
        notion_pending = 0
        if self.settings.notion_enabled and self.settings.notion_auto_sync and self.settings.notion_database_id:
            try:
                from ..integrations.notion_client import sync_jobs_to_notion
                cap = self.settings.notion_max_sync_per_run
                sync_res = sync_jobs_to_notion(db_path=self.db_path, limit=cap if cap and cap > 0 else None)
                notion_synced = sync_res.get("synced", 0)
                notion_pending = _count_unsynced(self.db_path)
                from ..integrations.notion_client import sync_closed_status
                sync_closed_status(api_token=self.settings.notion_api_token, db_path=self.db_path)
                if notion_synced > 0:
                    logger.info(f"[Notion Sync] Automatically synced {notion_synced} new jobs to Notion table.")
            except Exception as err:
                logger.warning(f"[Notion Sync] Auto-sync to Notion skipped: {err}")

        return {
            "tier_counts": tier_counts,
            "total_discovered": len(all_jobs),
            "matching_filtered": len(target_dicts),
            "net_new_inserted": net_new,
            "duplicates_prevented": duplicates_prevented,
            "harvested_companies": harvested_count,
            "registry_seeded": self.registry_seeded,
            "network_unavailable": self.network_unavailable,
            "notion_synced": notion_synced,
            "notion_pending": notion_pending,
            "jobs_closed": jobs_closed,
            "stale_closed": stale_closed,
            "too_old_skipped": too_old_skipped,
            "baseline_skipped": baseline_skipped,
            "jobs_reopened": jobs_reopened,
            "jobs": all_jobs,
        }
