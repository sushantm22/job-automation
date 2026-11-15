from src.answer_bank import AnswerBank
from src.answer_resolution import resolve_form_fields


def test_answer_bank_normalizes_and_finds_exact_match():
    bank = AnswerBank()
    bank.save_answer("what is your notice period", "45 days", field_type="text")

    answer = bank.lookup("Notice Period")

    assert answer == "45 days"


def test_profile_mapping_uses_profile_values_for_common_fields():
    profile = {
        "personal": {
            "first_name": "Manasvee",
            "last_name": "Rathie",
            "email": "manasvee@example.com",
            "phone": "+91 9876543210",
            "linkedin": "https://linkedin.com/in/manasvee",
            "github": "https://github.com/manasvee",
            "portfolio": "https://manasvee.dev",
        }
    }

    fields = [
        {"name": "first_name", "label": "First Name", "type": "text"},
        {"name": "last_name", "label": "Last Name", "type": "text"},
        {"name": "email", "label": "Email", "type": "email"},
        {"name": "phone", "label": "Phone", "type": "tel"},
        {"name": "linkedin", "label": "LinkedIn", "type": "url"},
        {"name": "portfolio_url", "label": "Portfolio URL", "type": "url"},
    ]

    results = resolve_form_fields(fields, profile, answer_bank=AnswerBank())
    values = {result["name"]: result["value"] for result in results if result.get("value") is not None}

    assert values["first_name"] == "Manasvee"
    assert values["last_name"] == "Rathie"
    assert values["email"] == "manasvee@example.com"
    assert values["phone"] == "+91 9876543210"
    assert values["linkedin"] == "https://linkedin.com/in/manasvee"
    assert values["portfolio_url"] == "https://manasvee.dev"


def test_sensitive_unmatched_question_marks_needs_human():
    profile = {"personal": {"first_name": "Manasvee"}}
    fields = [{"name": "criminal_history", "label": "Have you ever been convicted of a crime?", "type": "radio"}]

    results = resolve_form_fields(fields, profile, answer_bank=AnswerBank())

    assert results[0]["needs_human"] is True
    assert results[0]["source"] == "needs_human"
