from __future__ import annotations

import logging
from typing import Any
from urllib.error import HTTPError

from ..config import Settings, load_settings
from ..db import DB_PATH, get_connection, mark_company_checked, upsert_jobs
from ..utils.net import never_reached_server
from .apify_adapter import fetch_apify_naukri_jobs
from .ashby import fetch_ashby_jobs
from .base import JobRecord
from .firecrawl_adapter import fetch_firecrawl_portal_jobs
from .greenhouse import fetch_greenhouse_jobs
from .jobspy_adapter import fetch_jobspy_jobs
from .lever import fetch_lever_jobs
from .registry import CompanyRegistry
from .smartrecruiters import fetch_smartrecruiters_jobs

logger = logging.getLogger(__name__)


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

    def run_tier1_direct_apis(self, company_limit: int | None = 50) -> list[JobRecord]:
        """
        Tier 1: High-speed, 100% free direct API polling for tracked ATS boards
        (Greenhouse, Lever, Ashby, SmartRecruiters).
        Polls the least-recently-checked boards first so `company_limit` rotates through the registry.
        """
        self.registry_seeded = self.registry.ensure_seeded()
        slugs_by_platform = self.registry.get_slugs_by_platform(limit=company_limit, stale_first=True)
        discovered: list[JobRecord] = []
        polled = offline_failures = 0

        for platform, slugs in slugs_by_platform.items():
            for slug in slugs:
                try:
                    if platform == "greenhouse":
                        jobs = fetch_greenhouse_jobs(slug)
                    elif platform == "lever":
                        jobs = fetch_lever_jobs(slug)
                    elif platform == "ashby":
                        jobs = fetch_ashby_jobs(slug)
                    elif platform == "smartrecruiters":
                        jobs = fetch_smartrecruiters_jobs(slug)
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
        )

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
        active_tiers = set(selected_tiers or [1, 2, 3, 4])
        all_jobs: list[JobRecord] = []
        tier_counts: dict[str, int] = {
            "tier1_direct_apis": 0,
            "tier2_jobspy": 0,
            "tier3_apify": 0,
            "tier4_firecrawl": 0,
        }

        # 1. Tier 1: Direct APIs
        if 1 in active_tiers and self.settings.tier1_direct_apis:
            t1_jobs = self.run_tier1_direct_apis(company_limit=company_limit)
            tier_counts["tier1_direct_apis"] = len(t1_jobs)
            all_jobs.extend(t1_jobs)

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

        # 6. Deduplication & Persistence in SQLite
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
            for j in all_jobs
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

        # 7. Optional Automatic Notion Database Sync
        notion_synced = 0
        if self.settings.notion_enabled and self.settings.notion_auto_sync and self.settings.notion_database_id:
            try:
                from ..integrations.notion_client import sync_jobs_to_notion
                sync_res = sync_jobs_to_notion(db_path=self.db_path, limit=None)
                notion_synced = sync_res.get("synced", 0)
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
            "jobs": all_jobs,
        }
