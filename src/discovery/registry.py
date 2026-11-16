from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
import yaml

from src.db import DB_PATH, get_company_stats, list_companies, upsert_company
from .harvester import extract_ats_slugs, probe_company_board

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "seeds" / "companies_seed.json"
DEFAULT_YAML_PATH = Path(__file__).resolve().parent / "companies.yaml"

# Top-level keys in companies.yaml that hold ATS slug lists owned by the SQLite registry.
# Every other key (e.g. `enterprise_portals` for Tier 4) is hand-maintained and must be preserved.
ATS_PLATFORM_KEYS = {"greenhouse", "lever", "ashby", "smartrecruiters"}


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


class CompanyRegistry:
    """Manages the durable company ATS registry with SQLite and YAML synchronization."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    def import_from_seed(self, seed_path: Path | str = DEFAULT_SEED_PATH) -> int:
        """Loads companies from a JSON seed file into SQLite company_registry."""
        path = Path(seed_path)
        if not path.exists():
            logger.warning("Seed file %s does not exist.", path)
            return 0

        with path.open("r", encoding="utf-8") as handle:
            seed_data = json.load(handle)

        inserted_count = 0
        for platform, slugs in seed_data.items():
            for slug in slugs:
                clean_slug = str(slug).strip()
                if not clean_slug:
                    continue
                is_new = upsert_company(
                    platform=platform,
                    slug=clean_slug,
                    status="active",
                    discovered_via="seed",
                    db_path=self.db_path,
                )
                if is_new:
                    inserted_count += 1

        logger.info("Imported %d new companies from seed (%s).", inserted_count, path)
        return inserted_count

    def harvest_from_urls(self, urls: list[str]) -> int:
        """
        Opportunistically extracts ATS slugs from a batch of URLs, validates them,
        and registers newly discovered companies.
        """
        combined_text = "\n".join([str(u) for u in urls if u])
        candidates = extract_ats_slugs(combined_text)
        if not candidates:
            return 0

        # Fetch existing companies to avoid redundant probes
        existing_rows = list_companies(status=None, db_path=self.db_path)
        existing_keys = {(r["platform"], r["slug"].lower()) for r in existing_rows}

        newly_registered = 0
        for item in candidates:
            platform = item["platform"]
            slug = item["slug"]
            key = (platform, slug.lower())

            if key in existing_keys:
                continue

            # Probe the board to ensure it's a real company
            probe = probe_company_board(platform, slug, timeout=5.0)
            if probe.get("valid") and probe.get("job_count", 0) >= 0:
                is_new = upsert_company(
                    platform=platform,
                    slug=slug,
                    name=probe.get("name"),
                    status=probe.get("status", "active"),
                    job_count=probe.get("job_count", 0),
                    discovered_via="auto_harvest",
                    db_path=self.db_path,
                )
                if is_new:
                    newly_registered += 1
                    existing_keys.add(key)
                    logger.info("Auto-harvested new company: [%s] %s (jobs: %d)", platform, slug, probe.get("job_count", 0))

        return newly_registered

    def sync_to_yaml(self, yaml_path: Path | str = DEFAULT_YAML_PATH) -> int:
        """
        Exports all active companies from SQLite to companies.yaml, rewriting only the
        ATS platform lists and preserving other sections such as `enterprise_portals`.
        """
        rows = list_companies(status="active", db_path=self.db_path)
        path = Path(yaml_path)
        preserved = {
            key: value for key, value in _load_yaml_dict(path).items() if key not in ATS_PLATFORM_KEYS
        }
        grouped: dict[str, Any] = {}

        for r in rows:
            platform = r["platform"]
            slug = r["slug"]
            grouped.setdefault(platform, []).append(slug)

        # Sort slugs for stability
        for p in grouped:
            grouped[p] = sorted(list(set(grouped[p])))

        grouped.update(preserved)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(grouped, handle, sort_keys=True)

        return len(rows)

    def sync_from_yaml(self, yaml_path: Path | str = DEFAULT_YAML_PATH) -> int:
        """Reads companies.yaml and imports any missing companies into SQLite."""
        data = _load_yaml_dict(Path(yaml_path))

        inserted = 0
        for platform, slugs in data.items():
            if platform not in ATS_PLATFORM_KEYS or not isinstance(slugs, list):
                continue
            for slug in slugs:
                if not isinstance(slug, str) or not slug.strip():
                    continue
                is_new = upsert_company(
                    platform=platform,
                    slug=str(slug).strip(),
                    status="active",
                    discovered_via="yaml_sync",
                    db_path=self.db_path,
                )
                if is_new:
                    inserted += 1

        return inserted

    def ensure_seeded(self, yaml_path: Path | str = DEFAULT_YAML_PATH) -> int:
        """
        Adds every company listed in companies.yaml that this registry has never seen: all of them
        on a fresh clone / new DATABASE_PATH, and newly curated entries (e.g. a new platform) for
        existing users. Companies already in the registry are left untouched, so boards pruned to
        inactive stay pruned. Returns the number added.
        """
        data = _load_yaml_dict(Path(yaml_path))
        known = {(r["platform"], r["slug"].lower()) for r in list_companies(status=None, db_path=self.db_path)}
        added = 0
        for platform, slugs in data.items():
            if platform not in ATS_PLATFORM_KEYS or not isinstance(slugs, list):
                continue
            for slug in slugs:
                if not isinstance(slug, str) or not slug.strip() or (platform, slug.strip().lower()) in known:
                    continue
                if upsert_company(platform=platform, slug=slug.strip(), status="active",
                                  discovered_via="yaml_sync", db_path=self.db_path):
                    added += 1
        if added:
            logger.info("Added %d companies from %s to the registry.", added, yaml_path)
        return added

    def get_slugs_by_platform(
        self,
        platform: str | None = None,
        limit: int | None = None,
        stale_first: bool = False,
    ) -> dict[str, list[str]]:
        """Returns active slugs grouped by platform (least-recently-checked first if `stale_first`)."""
        rows = list_companies(
            platform=platform, status="active", limit=limit, db_path=self.db_path, stale_first=stale_first
        )
        grouped: dict[str, list[str]] = {}
        for r in rows:
            grouped.setdefault(r["platform"], []).append(r["slug"])
        return grouped

    def get_stats(self) -> dict[str, Any]:
        """Returns statistics from the company registry."""
        return get_company_stats(self.db_path)
