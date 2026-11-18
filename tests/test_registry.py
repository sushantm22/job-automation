from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from src.db import init_db
from src.discovery.registry import CompanyRegistry


def test_registry_seed_import_and_sync(tmp_path: Path):
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    seed_file = tmp_path / "seed.json"
    seed_data = {
        "greenhouse": ["stripe", "databricks"],
        "lever": ["plivo"],
        "ashby": ["sentry"],
    }
    with seed_file.open("w", encoding="utf-8") as f:
        json.dump(seed_data, f)

    registry = CompanyRegistry(db_path=db_file)
    inserted = registry.import_from_seed(seed_file)
    assert inserted == 4

    # Duplicate import should not insert again
    inserted_again = registry.import_from_seed(seed_file)
    assert inserted_again == 0

    stats = registry.get_stats()
    assert stats["total_companies"] == 4
    assert stats["by_platform"]["greenhouse"]["count"] == 2
    assert stats["by_platform"]["lever"]["count"] == 1
    assert stats["by_platform"]["ashby"]["count"] == 1

    # Test sync to yaml
    yaml_file = tmp_path / "companies.yaml"
    synced_count = registry.sync_to_yaml(yaml_file)
    assert synced_count == 4
    assert yaml_file.exists()


@patch("src.discovery.registry.probe_company_board")
def test_registry_harvest_from_urls(mock_probe, tmp_path: Path):
    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)

    registry = CompanyRegistry(db_path=db_file)

    mock_probe.return_value = {
        "valid": True,
        "platform": "greenhouse",
        "slug": "airbnb",
        "name": "Airbnb",
        "job_count": 5,
        "status": "active",
        "error": None,
    }

    urls = [
        "https://boards.greenhouse.io/airbnb/jobs/999",
        "https://boards.greenhouse.io/airbnb/jobs/888",  # duplicate in batch
    ]

    newly_registered = registry.harvest_from_urls(urls)
    assert newly_registered == 1

    # Harvesting again should not re-register
    assert registry.harvest_from_urls(urls) == 0

    stats = registry.get_stats()
    assert stats["total_companies"] == 1
    assert stats["by_source"]["auto_harvest"] == 1


def test_sync_to_yaml_preserves_enterprise_portals(tmp_path: Path):
    import yaml

    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)
    registry = CompanyRegistry(db_path=db_file)

    yaml_file = tmp_path / "companies.yaml"
    portals = [{"name": "Google", "url": "https://careers.google.com"}]
    yaml_file.write_text(
        yaml.safe_dump({"greenhouse": ["stale-board"], "enterprise_portals": portals}), encoding="utf-8"
    )

    # Portal entries must not be imported as company slugs.
    assert registry.sync_from_yaml(yaml_file) == 1
    assert registry.get_slugs_by_platform() == {"greenhouse": ["stale-board"]}

    from src.db import upsert_company
    upsert_company("greenhouse", "stale-board", status="inactive", db_path=db_file)
    upsert_company("lever", "plivo", db_path=db_file)
    registry.sync_to_yaml(yaml_file)

    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    assert data["enterprise_portals"] == portals
    assert data["lever"] == ["plivo"]
    assert "greenhouse" not in data  # inactive boards are still dropped from the ATS lists


def test_tier1_rotates_through_registry_across_runs(tmp_path: Path):
    from src.config import Settings
    from src.db import upsert_company
    from src.discovery.engine import JobDiscoveryEngine

    db_file = tmp_path / "test_jobs.db"
    init_db(db_file)
    for slug, jobs in [("big", 50), ("mid", 20), ("small", 1)]:
        upsert_company("greenhouse", slug, job_count=jobs, db_path=db_file)

    engine = JobDiscoveryEngine(settings=Settings(), db_path=db_file)
    polled: list[str] = []

    def fake_fetch(slug):
        polled.append(slug)
        if slug == "mid":
            raise RuntimeError("board down")
        return []

    with patch.object(engine.registry, "ensure_seeded", return_value=0), \
         patch("src.discovery.engine.fetch_greenhouse_jobs", side_effect=fake_fetch):
        for _ in range(3):
            engine.run_tier1_direct_apis(company_limit=2)

    # Run 1 takes the two biggest; run 2 must start with the board run 1 skipped. Before the fix,
    # every run re-polled ["big", "mid"] and "small" was never reached. A failing board ("mid")
    # is still stamped, so it doesn't pin itself to the front of the rotation.
    assert polled[:2] == ["big", "mid"]
    assert polled[2] == "small"
    assert set(polled) == {"big", "mid", "small"}
