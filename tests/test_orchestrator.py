from src.orchestrator import JobApplicationOrchestrator


def test_orchestrator_filters_and_scores_jobs():
    orchestrator = JobApplicationOrchestrator()

    filtered = orchestrator.discover_jobs(
        [
            {
                "title": "Backend Engineer",
                "location": "Remote",
                "description": "Build Python APIs and services",
                "company": "Example",
                "source": "greenhouse",
                "url": "https://example.com/job/1",
            },
            {
                "title": "Marketing Manager",
                "location": "Remote",
                "description": "Drive campaigns and brand strategy",
                "company": "Example",
                "source": "greenhouse",
                "url": "https://example.com/job/2",
            },
        ],
        keywords=["backend engineer"],
        locations=["remote"],
        exclude=["intern"],
    )

    assert len(filtered) == 1
    assert filtered[0]["title"] == "Backend Engineer"

    scored = orchestrator.score_jobs(filtered, profile_summary={"skills": ["python"], "experience": ["backend"]})
    assert len(scored) == 1
    assert scored[0]["score"] >= 0
    assert scored[0]["reason"]


def test_orchestrator_prepares_review_rows_from_resolved_fields():
    orchestrator = JobApplicationOrchestrator()

    resolved = [
        {"name": "first_name", "label": "First name", "value": "Ada", "source": "profile", "needs_human": False},
        {"name": "salary", "label": "Salary expectation", "value": None, "source": "needs_human", "needs_human": True},
    ]

    rows = orchestrator.review_rows(resolved)

    assert rows[0]["question"] == "First name"
    assert rows[1]["needs_human"] is True
