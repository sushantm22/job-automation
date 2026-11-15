import asyncio

from src.apply.greenhouse import GreenhouseAdapter


class FakePage:
    def __init__(self, html: str):
        self._html = html

    async def goto(self, url):
        self.url = url
        return None

    async def content(self):
        return self._html


def test_greenhouse_adapter_matches_url():
    adapter = GreenhouseAdapter()

    assert adapter.matches("https://boards.greenhouse.io/company/jobs/123")
    assert adapter.matches("https://job-boards.greenhouse.io/company/jobs/123")
    assert not adapter.matches("https://jobs.lever.co/example/123")


def test_greenhouse_adapter_extracts_form_fields_from_html():
    html = """
    <html><body>
      <form>
        <label for="first_name">First Name</label>
        <input id="first_name" name="first_name" type="text" required>

        <label for="email">Email</label>
        <input id="email" name="email" type="email" required>

        <label for="resume">Resume</label>
        <input id="resume" name="resume" type="file" required>
      </form>
    </body></html>
    """
    adapter = GreenhouseAdapter()

    fields = asyncio.run(adapter.extract_fields(FakePage(html)))
    names = {field["name"] for field in fields}

    assert "first_name" in names
    assert "email" in names
    assert "resume" in names
    assert any(field["type"] == "file" and field["name"] == "resume" for field in fields)


def test_greenhouse_fill_respects_review_mode_without_submit():
    adapter = GreenhouseAdapter()
    resolved = [
        {"name": "first_name", "value": "Manasvee", "source": "profile"},
        {"name": "email", "value": "manasvee@example.com", "source": "profile"},
    ]

    result = asyncio.run(adapter.fill(FakePage("<form></form>"), resolved, review_mode=True))

    assert result is True
