import sqlite3

from src.db import init_db, upsert_jobs


def test_init_db_creates_required_tables(tmp_path):
    db_path = tmp_path / "jobs.db"

    returned_path = init_db(db_path)

    assert returned_path == db_path

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        }

    assert {"jobs", "applications", "answers", "answer_bank"}.issubset(tables)


def test_upsert_jobs_counts_only_new_rows(tmp_path):
    db_path = tmp_path / "jobs.db"
    init_db(db_path)

    inserted = upsert_jobs(
        [
            {"source": "greenhouse", "company": "Acme", "title": "Engineer", "location": "Remote", "url": "https://one.example", "description": "desc"},
            {"source": "greenhouse", "company": "Acme", "title": "Engineer II", "location": "Remote", "url": "https://two.example", "description": "desc"},
            {"source": "greenhouse", "company": "Acme", "title": "Engineer", "location": "Remote", "url": "https://one.example", "description": "desc"},
        ],
        db_path,
    )

    assert inserted == 2
