from src.stats import summarize_applications
from src.tailoring import build_resume_summary


def test_build_resume_summary_uses_profile_only():
    profile = {
        "personal": {"first_name": "Manasvee", "last_name": "Rathie"},
        "experience": [{"company": "Uni Cards", "title": "Software Engineer"}],
        "skills": ["Python", "Java", "Kafka"],
    }

    summary = build_resume_summary(profile, role="Backend Engineer")

    assert "Manasvee" in summary
    assert "Uni Cards" in summary
    assert "Backend Engineer" in summary
    assert "Python" in summary


def test_summarize_applications_handles_empty_data():
    stats = summarize_applications([])

    assert stats["total_applications"] == 0
    assert stats["average_calls_per_application"] == 0
    assert stats["average_tokens_per_application"] == 0
