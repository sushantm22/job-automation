from src.models import JobMatchResult
from src.scoring import hard_filter_jobs, score_job
from src.llm.base import MockLLMClient


def test_hard_filter_skips_excluded_and_non_matching_jobs():
    jobs = [
        {"title": "Python Engineer", "location": "Remote", "description": "Backend Python developer role."},
        {"title": "Internship", "location": "Remote", "description": "Unpaid internship."},
        {"title": "Data Analyst", "location": "New York", "description": "Analyze data."},
    ]

    filtered = hard_filter_jobs(jobs, keywords=["python"], locations=["Remote"], exclude=["intern", "unpaid"])

    assert len(filtered) == 1
    assert filtered[0]["title"] == "Python Engineer"


def test_score_job_returns_validation_result():
    llm = MockLLMClient({
        "score": 88,
        "reason": "Strong Python backend match with remote preference.",
        "missing_requirements": [],
        "deal_breakers": [],
    })

    result = score_job({
        "title": "Python Engineer",
        "description": "Build backend services with Python, FastAPI, and SQL.",
        "location": "Remote",
    }, profile_summary={"skills": ["Python", "FastAPI"], "experience": ["backend systems"]}, llm=llm)

    assert isinstance(result, JobMatchResult)
    assert result.score == 88
    assert result.reason


def test_hard_filter_rejects_foreign_and_unrelated_jobs():
    jobs = [
        {"title": "SDET Lead", "location": "Bengaluru, India", "description": "QA automation lead"},
        {"title": "Senior SDET", "location": "Remote, India", "description": "SDET role"},
        {"title": "QA Automation Engineer", "location": "Remote", "description": "Automation engineer"},
        {"title": "Account Executive", "location": "Tokyo, Japan", "description": "Sales role with QA collaboration"},
        {"title": "Software Engineer", "location": "Remote, Tokyo, Japan", "description": "Tokyo remote role"},
        {"title": "Delivery Solutions Architect", "location": "Remote - Colorado, United States", "description": "Testing architecture"},
        {"title": "Consumer Marketing Manager", "location": "London, UK", "description": "Marketing lead"},
        {"title": "AI Sales Director", "location": "San Francisco, California", "description": "Sales director"},
    ]

    keywords = ["SDET Lead", "Senior SDET", "QA Automation Engineer"]
    locations = ["India", "Remote", "Bengaluru"]
    exclude = ["intern"]

    filtered = hard_filter_jobs(jobs, keywords=keywords, locations=locations, exclude=exclude)

    titles = [j["title"] for j in filtered]
    assert "SDET Lead" in titles
    assert "Senior SDET" in titles
    assert "QA Automation Engineer" in titles
    assert len(filtered) == 3


def test_hard_filter_exclude_matches_whole_words_only():
    jobs = [
        {"title": "Senior SDET", "location": "Bengaluru, India", "description": "Work with international teams on internal tools."},
        {"title": "SDET Internship", "location": "Bengaluru, India", "description": "Summer program."},
        {"title": "SDET Intern", "location": "Pune, India", "description": "Six month program."},
    ]

    filtered = hard_filter_jobs(jobs, keywords=["SDET"], locations=["India"], exclude=["intern", "unpaid"])

    assert [j["title"] for j in filtered] == ["Senior SDET"]


def test_hard_filter_keeps_user_roles_on_unrelated_list_and_skips_qa_fallback():
    jobs = [
        {"title": "Area Sales Manager", "location": "Pune, India", "description": "Drive regional sales."},
        {"title": "Senior Sales Manager", "location": "Remote", "description": "Own enterprise accounts."},
        {"title": "Account Executive", "location": "Mumbai, India", "description": "Close deals."},
        {"title": "QA Automation Engineer", "location": "Bengaluru, India", "description": "Selenium tests."},
    ]

    filtered = hard_filter_jobs(
        jobs, keywords=["Senior Sales Manager", "Area Sales Manager"], locations=["India", "Remote"], exclude=["intern"]
    )

    assert [j["title"] for j in filtered] == ["Area Sales Manager", "Senior Sales Manager"]
