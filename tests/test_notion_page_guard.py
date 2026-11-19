"""init-notion-db must not quietly add a second table to a page that was set up before
(an assistant reused an old page link from an earlier chat instead of asking)."""
from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from src.cli import app
from src.integrations import notion_client

PAGE = "https://app.notion.com/p/business-role-testing-41bb2bd2706980109cbcf3eeaa309a45?source=copy_link"


def _blocks(*items, has_more=False, next_cursor=None):
    return {"results": list(items), "has_more": has_more, "next_cursor": next_cursor}


def test_find_job_tables_lists_only_this_projects_tables():
    pages = [
        _blocks(
            {"type": "child_database", "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "child_database": {"title": "Automated Job Applications"}},
            {"type": "child_database", "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "child_database": {"title": "Reading list"}},
            {"type": "paragraph", "id": "c" * 32},
            has_more=True, next_cursor="next",
        ),
        _blocks(
            {"type": "child_database", "id": "d" * 32, "child_database": {"title": "Job Opportunities"}},
            {"type": "child_database", "id": "e" * 32, "archived": True, "child_database": {"title": "Automated Job Applications"}},
        ),
    ]
    urls = []

    def fake_send(req, timeout):
        urls.append(req.full_url)
        return pages[len(urls) - 1]

    with patch.object(notion_client, "_send_json", side_effect=fake_send):
        tables = notion_client.find_job_tables(PAGE, api_token="ntn_x")
    assert [t["id"] for t in tables] == ["a" * 32, "d" * 32]  # other titles and archived tables ignored
    assert "/blocks/41bb2bd2706980109cbcf3eeaa309a45/children" in urls[0] and "start_cursor=next" in urls[1]


def test_init_notion_db_stops_when_the_page_already_has_a_job_table():
    existing = [{"id": "a" * 32, "title": "Automated Job Applications", "url": "https://www.notion.so/" + "a" * 32}]
    with patch("src.integrations.notion_client.find_job_tables", return_value=existing), \
         patch("src.integrations.notion_client.create_notion_job_database") as create, \
         patch("src.onboarding.write_env_file") as write_env:
        result = CliRunner().invoke(app, ["init-notion-db", "--parent-page-id", PAGE])
    assert result.exit_code == 2
    assert "already has a job table" in result.output and "--create-new" in result.output
    create.assert_not_called()
    write_env.assert_not_called()


def test_create_new_adds_a_table_without_checking():
    with patch("src.integrations.notion_client.find_job_tables") as check, \
         patch("src.integrations.notion_client.create_notion_job_database", return_value={"id": "f" * 32, "url": "u"}), \
         patch("src.onboarding.write_env_file"):
        result = CliRunner().invoke(app, ["init-notion-db", "--parent-page-id", PAGE, "--create-new"])
    assert result.exit_code == 0, result.output
    check.assert_not_called()


def test_a_failed_check_does_not_block_creating_the_table():
    with patch("src.integrations.notion_client.find_job_tables", side_effect=OSError("offline")), \
         patch("src.integrations.notion_client.create_notion_job_database", return_value={"id": "f" * 32, "url": "u"}) as create, \
         patch("src.onboarding.write_env_file"):
        result = CliRunner().invoke(app, ["init-notion-db", "--parent-page-id", PAGE])
    assert result.exit_code == 0, result.output
    create.assert_called_once()
