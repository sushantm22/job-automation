from pathlib import Path

from src.utils.dom import extract_form_fields

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_greenhouse_fields_from_fixture():
    html = (FIXTURES / "greenhouse_form.html").read_text(encoding="utf-8")

    fields = extract_form_fields(html)

    names = {field["name"] for field in fields}
    assert "first_name" in names
    assert "email" in names
    assert "resume" in names
    assert any(field["type"] == "file" and field["name"] == "resume" for field in fields)


def test_extract_lever_fields_from_fixture():
    html = (FIXTURES / "lever_form.html").read_text(encoding="utf-8")

    fields = extract_form_fields(html)

    names = {field["name"] for field in fields}
    assert "phone" in names
    assert "department" in names
    assert any(field["type"] == "select" and field["name"] == "department" for field in fields)


def test_extract_ashby_fields_from_fixture():
    html = (FIXTURES / "ashby_form.html").read_text(encoding="utf-8")

    fields = extract_form_fields(html)

    names = {field["name"] for field in fields}
    assert "portfolio_url" in names
    assert "visa_status" in names
    assert any(field["type"] == "radio" and field["name"] == "visa_status" for field in fields)
    assert any(field["type"] == "checkbox" and field["name"] == "remote_work" for field in fields)
