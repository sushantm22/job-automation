from unittest.mock import patch
import pandas as pd
from src.discovery.ashby import parse_ashby_jobs
from src.discovery.greenhouse import parse_greenhouse_jobs
from src.discovery.jobspy_adapter import fetch_jobspy_jobs, parse_jobspy_dataframe
from src.discovery.lever import parse_lever_jobs


def test_parse_greenhouse_jobs_extracts_job_fields():
    payload = {
        "jobs": [
            {
                "id": 101,
                "title": "Senior Python Engineer",
                "location": {"name": "Remote - Bengaluru"},
                "absolute_url": "https://boards.greenhouse.io/company/jobs/101",
                "content": "<p>Build backend services with Python and SQL.</p>",
                "updated_at": "2026-10-01T12:00:00Z",
            }
        ]
    }

    jobs = parse_greenhouse_jobs(payload)

    assert len(jobs) == 1
    assert jobs[0].source == "greenhouse"
    assert jobs[0].title == "Senior Python Engineer"
    assert jobs[0].location == "Remote - Bengaluru"
    assert jobs[0].url == "https://boards.greenhouse.io/company/jobs/101"
    assert "Python" in jobs[0].description


def test_parse_lever_jobs_extracts_job_fields():
    payload = [
        {
            "id": "lever-1",
            "text": "Backend Engineer",
            "categories": {"location": "Bengaluru, India"},
            "hostedUrl": "https://jobs.lever.co/example/abc123",
            "description": "<p>We are hiring a backend engineer with Python experience.</p>",
            "createdAt": 1727770000000,
        }
    ]

    jobs = parse_lever_jobs(payload)

    assert len(jobs) == 1
    assert jobs[0].source == "lever"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].location == "Bengaluru, India"
    assert jobs[0].url == "https://jobs.lever.co/example/abc123"
    assert "Python" in jobs[0].description


def test_parse_ashby_jobs_extracts_job_fields():
    payload = {
        "jobs": [
            {
                "id": "ashby-1",
                "title": "Software Engineer, Infrastructure",
                "location": "Bengaluru, India",
                "isRemote": True,
                "jobUrl": "https://jobs.ashbyhq.com/example/ashby-1",
                "descriptionPlain": "Develop cloud infrastructure with Python.",
                "publishedAt": "2026-10-05T00:00:00.000Z",
            }
        ]
    }

    jobs = parse_ashby_jobs(payload, company_slug="example")

    assert len(jobs) == 1
    assert jobs[0].source == "ashby"
    assert jobs[0].company == "Example"
    assert jobs[0].title == "Software Engineer, Infrastructure"
    assert "Remote" in jobs[0].location
    assert jobs[0].url == "https://jobs.ashbyhq.com/example/ashby-1"
    assert "Python" in jobs[0].description


def test_parse_jobspy_dataframe_handles_india_and_remote():
    df = pd.DataFrame(
        [
            {
                "site": "naukri",
                "company": "Tech Corp India",
                "title": "Senior Python Developer",
                "location": "Bengaluru, Hyderabad, India",
                "job_url_direct": "https://www.naukri.com/job-123",
                "job_url": "https://www.naukri.com/job-123",
                "description": "Python, Django, FastAPI backend systems.",
                "date_posted": "2026-11-01",
                "is_remote": False,
            },
            {
                "site": "indeed",
                "company": "Cloud Global",
                "title": "Backend Software Engineer",
                "location": "India",
                "job_url_direct": "https://in.indeed.com/viewjob?jk=abc",
                "job_url": "https://in.indeed.com/viewjob?jk=abc",
                "description": "Distributed systems in Python.",
                "date_posted": "2026-11-02",
                "is_remote": True,
            },
        ]
    )

    records = parse_jobspy_dataframe(df)

    assert len(records) == 2
    assert records[0].source == "naukri"
    assert records[0].company == "Tech Corp India"
    assert "India" in records[0].location
    assert records[0].url == "https://www.naukri.com/job-123"

    assert records[1].source == "indeed"
    assert "Remote" in records[1].location
    assert records[1].company == "Cloud Global"


@patch("jobspy.scrape_jobs")
def test_fetch_jobspy_jobs_queries_india_and_remote(mock_scrape):
    mock_scrape.return_value = pd.DataFrame(
        [
            {
                "site": "linkedin",
                "company": "Stripe India",
                "title": "Backend Engineer",
                "location": "Bengaluru, India",
                "job_url_direct": "https://www.linkedin.com/jobs/view/100",
                "description": "Scale payment systems with Python and Ruby.",
                "date_posted": "2026-11-03",
                "is_remote": False,
            }
        ]
    )

    records = fetch_jobspy_jobs(
        keywords=["backend engineer"],
        locations=["India"],
        results_wanted=5,
        include_remote=True,
    )

    assert len(records) == 1
    assert records[0].source == "linkedin"
    assert records[0].company == "Stripe India"
    assert mock_scrape.called


def test_parse_greenhouse_jobs_uses_per_job_company_name():
    # The real /v1/boards/{slug}/jobs payload has no board-level "name"; each job has company_name.
    payload = {
        "jobs": [
            {
                "title": "Senior SDET",
                "company_name": "Stripe",
                "location": {"name": "Bengaluru, India"},
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1",
            }
        ]
    }
    assert parse_greenhouse_jobs(payload, company_slug="stripe")[0].company == "Stripe"


def test_parse_greenhouse_and_lever_fall_back_to_slug_name():
    gh_payload = {"jobs": [{"title": "QA Lead", "absolute_url": "https://boards.greenhouse.io/x/jobs/1"}]}
    lever_payload = [{"text": "QA Lead", "hostedUrl": "https://jobs.lever.co/acme-labs/1"}]

    assert parse_greenhouse_jobs(gh_payload, company_slug="acme-labs")[0].company == "Acme Labs"
    assert parse_lever_jobs(lever_payload, company_slug="acme-labs")[0].company == "Acme Labs"
