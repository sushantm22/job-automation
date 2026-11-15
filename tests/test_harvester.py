from __future__ import annotations

from unittest.mock import MagicMock, patch
from src.discovery.harvester import extract_ats_slugs, probe_company_board, resolve_domain_to_ats


def test_extract_ats_slugs_finds_all_platforms():
    text = """
    Check out these jobs:
    https://boards.greenhouse.io/stripe/jobs/12345
    https://job-boards.greenhouse.io/databricks/jobs/67890
    https://boards.greenhouse.io/embed/job_board?for=coinbase
    https://jobs.lever.co/plivo/abc-def
    https://jobs.ashbyhq.com/sentry/xyz-789
    https://jobs.smartrecruiters.com/Grab/12345
    """

    slugs = extract_ats_slugs(text)

    expected = [
        {"platform": "greenhouse", "slug": "coinbase"},
        {"platform": "greenhouse", "slug": "stripe"},
        {"platform": "greenhouse", "slug": "databricks"},
        {"platform": "lever", "slug": "plivo"},
        {"platform": "ashby", "slug": "sentry"},
        {"platform": "smartrecruiters", "slug": "Grab"},
    ]

    for item in expected:
        assert item in slugs


def test_extract_ats_slugs_ignores_junk():
    text = """
    https://boards.greenhouse.io/api/v1/jobs
    https://jobs.lever.co/search
    https://jobs.ashbyhq.com/embed
    https://boards.greenhouse.io/static/main.js
    """

    slugs = extract_ats_slugs(text)
    assert len(slugs) == 0


@patch("urllib.request.urlopen")
def test_probe_company_board_greenhouse(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"jobs": [{"id": 1, "company_name": "Stripe", "title": "Dev"}]}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    result = probe_company_board("greenhouse", "stripe")

    assert result["valid"] is True
    assert result["platform"] == "greenhouse"
    assert result["slug"] == "stripe"
    assert result["job_count"] == 1
    assert result["name"] == "Stripe"
    assert result["status"] == "active"


@patch("urllib.request.urlopen")
def test_probe_company_board_not_found(mock_urlopen):
    import urllib.error
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    result = probe_company_board("greenhouse", "nonexistent-co-xyz-123")

    assert result["valid"] is False
    assert result["status"] == "not_found"
    assert result["job_count"] == 0


def test_resolve_domain_to_ats_with_direct_ats_url():
    url = "https://boards.greenhouse.io/datadog"
    resolved = resolve_domain_to_ats(url, verify_live=False)
    assert len(resolved) == 1
    assert resolved[0]["platform"] == "greenhouse"
    assert resolved[0]["slug"] == "datadog"
