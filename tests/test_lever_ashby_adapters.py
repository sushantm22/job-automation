import asyncio

from src.apply.ashby import AshbyAdapter
from src.apply.lever import LeverAdapter


class FakePage:
    def __init__(self, html: str):
        self._html = html

    async def content(self):
        return self._html


def test_lever_adapter_matches_url():
    adapter = LeverAdapter()

    assert adapter.matches("https://jobs.lever.co/example/abc123")
    assert not adapter.matches("https://boards.greenhouse.io/company/jobs/123")


def test_ashby_adapter_matches_url():
    adapter = AshbyAdapter()

    assert adapter.matches("https://jobs.ashbyhq.com/example/123")
    assert not adapter.matches("https://jobs.lever.co/example/123")


def test_lever_adapter_extracts_with_labels_and_selects():
    html = """
    <html><body>
      <form>
        <label for="name">Full Name</label>
        <input id="name" name="name" type="text" required>

        <label for="team">Team</label>
        <select id="team" name="team">
          <option value="">Choose</option>
          <option value="engineering">Engineering</option>
          <option value="data">Data</option>
        </select>
      </form>
    </body></html>
    """
    adapter = LeverAdapter()
    fields = asyncio.run(adapter.extract_fields(FakePage(html)))
    names = {field["name"] for field in fields}

    assert "name" in names
    assert "team" in names
    assert any(field["type"] == "select" and field["name"] == "team" for field in fields)


def test_ashby_adapter_extracts_radio_and_checkbox_groups():
    html = """
    <html><body>
      <form>
        <label for="portfolio_url">Portfolio URL</label>
        <input id="portfolio_url" name="portfolio_url" type="url">

        <p>Work authorization</p>
        <label><input type="radio" name="work_authorization" value="yes"> Yes</label>
        <label><input type="radio" name="work_authorization" value="no"> No</label>

        <label><input type="checkbox" name="remote_work" value="true"> Remote work</label>
      </form>
    </body></html>
    """
    adapter = AshbyAdapter()
    fields = asyncio.run(adapter.extract_fields(FakePage(html)))
    names = {field["name"] for field in fields}

    assert "portfolio_url" in names
    assert "work_authorization" in names
    assert "remote_work" in names
    assert any(field["type"] == "radio" and field["name"] == "work_authorization" for field in fields)
    assert any(field["type"] == "checkbox" and field["name"] == "remote_work" for field in fields)
