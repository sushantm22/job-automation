import pytest

from src.models import JobMatchResult
from src.scoring import hard_filter_jobs, score_job, title_matches_roles
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


def test_hard_filter_matches_the_users_roles_only_and_skips_qa_fallback():
    jobs = [
        {"title": "Area Sales Manager", "location": "Pune, India", "description": "Drive regional sales."},
        {"title": "Senior Sales Manager", "location": "Remote", "description": "Own enterprise accounts."},
        # Dropped because it is not one of the roles (no built-in list of "business" titles any more).
        {"title": "Account Executive", "location": "Mumbai, India", "description": "Close deals."},
        {"title": "QA Automation Engineer", "location": "Bengaluru, India", "description": "Selenium tests."},
    ]

    filtered = hard_filter_jobs(
        jobs, keywords=["Senior Sales Manager", "Area Sales Manager"], locations=["India", "Remote"], exclude=["intern"]
    )

    assert [j["title"] for j in filtered] == ["Area Sales Manager", "Senior Sales Manager"]


def test_any_role_can_be_searched_without_a_built_in_title_list():
    jobs = [
        {"title": "Account Executive", "location": "Mumbai, India", "description": ""},
        {"title": "Marketing Manager", "location": "Pune, India", "description": ""},
        {"title": "HR Business Partner", "location": "Remote", "description": ""},
    ]
    kept = hard_filter_jobs(jobs, keywords=["Account Executive", "Marketing Manager"], locations=["India"], exclude=[])
    assert [j["title"] for j in kept] == ["Account Executive", "Marketing Manager"]


def test_description_text_never_matches_a_role():
    jobs = [{"title": "Software Engineer 3 - GenAI", "location": "Bengaluru, India",
             "description": "Work with our sales and marketing teams on sales tooling."}]
    assert hard_filter_jobs(jobs, keywords=["Sales Manager"], locations=["India"], exclude=[]) == []


@pytest.mark.parametrize("title,roles", [
    ("Senior Sales Manager", ["Sales Manager"]),            # seniority ignored
    ("Sales Manager", ["Senior Sales Manager"]),
    ("Sr. Sales Manager", ["Senior Sales Manager"]),         # abbreviation
    ("Sales Mgr", ["Sales Manager"]),
    ("Asst. Manager - Sales", ["Sales Manager"]),            # reordered with qualifier
    ("Manager – Sales", ["Sales Manager"]),
    ("Manager, Inside Sales", ["Sales Manager"]),
    ("Head of Sales", ["Sales Head"]),
    ("Director of Marketing", ["Marketing Director"]),
    ("Sales & Marketing Manager", ["Marketing Manager"]),    # "&" split
    ("Sales & Marketing Manager", ["Sales Manager"]),
    ("Dy. Manager - Sales & Marketing", ["Sales Manager"]),
    ("BDM - Corporate Sales", ["Business Development Manager"]),
    ("Business Development Manager", ["BDM"]),
    ("KAM - Modern Trade", ["Key Account Manager"]),
    ("Human Resources Business Partner", ["HRBP"]),
    ("Vice President - Sales", ["VP Sales"]),
    ("FP&A Manager", ["FP&A Manager"]),                      # FP&A / L&D / R&D stay intact
    ("L&D Manager", ["L&D Manager"]),
    ("Senior Manager - Category Marketing", ["Sr manager - category marketing"]),
    ("Category Manager - E-Commerce", ["Category Manager"]),
    ("Python Engineer", ["python"]),
])
def test_title_matches_roles(title, roles):
    assert title_matches_roles(title, roles) is True


@pytest.mark.parametrize("title,roles", [
    ("Salesforce Developer", ["Sales"]),                      # whole words only
    ("Salesforce Developer", ["Sales Manager"]),
    ("Manager, Sales Operations", ["Sales Manager"]),
    ("Sales Engineer", ["Sales Manager"]),
    ("L&D Manager", ["R&D Manager"]),
    ("Marketing Manager", ["Sales Manager"]),
    ("", ["Sales Manager"]),
])
def test_title_does_not_match_other_roles(title, roles):
    assert title_matches_roles(title, roles) is False


def test_us_state_code_tn_is_not_tamil_nadu():
    jobs = [
        {"title": "Sales Manager", "location": "Nashville, TN, USA", "description": ""},
        {"title": "Sales Manager", "location": "Nashville, TN", "description": ""},
        {"title": "Sales Manager", "location": "Coimbatore, Tamil Nadu", "description": ""},
        {"title": "Sales Manager", "location": "Chennai", "description": ""},
    ]
    kept = hard_filter_jobs(jobs, keywords=["Sales Manager"], locations=["India", "Remote"], exclude=[])
    assert [j["location"] for j in kept] == ["Coimbatore, Tamil Nadu", "Chennai"]
