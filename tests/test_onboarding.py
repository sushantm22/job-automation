from __future__ import annotations

import os
from pathlib import Path
from src.config import Settings, load_settings
from src.db import init_db, reset_db, upsert_jobs
from src.onboarding import check_environment, read_env_file, write_env_file


def test_check_environment_returns_valid_structure():
    res = check_environment()
    assert "python_version" in res
    assert "valid_version" in res
    assert isinstance(res["valid_version"], bool)
    assert "is_venv" in res


def test_reset_db_clears_records_and_preserves_schema(tmp_path):
    test_db = tmp_path / "reset_test.db"
    init_db(test_db)

    # Insert sample job
    sample = [{
        "source": "test",
        "company": "TestCorp",
        "title": "SDET",
        "location": "Remote",
        "url": "https://example.com/job1",
    }]
    upsert_jobs(sample, db_path=test_db)

    res = reset_db(db_path=test_db)
    assert res["jobs_deleted"] == 1

    # Assert database still works and has 0 rows
    import sqlite3
    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
    conn.close()
    assert count == 0


def test_load_settings_honors_database_path_env(tmp_path, monkeypatch):
    custom_db = tmp_path / "custom_test.db"
    monkeypatch.setenv("DATABASE_PATH", str(custom_db))
    settings = load_settings()
    assert settings.database_path == custom_db
