import asyncio

from src.apply.fallback_agent import BrowserUseFallbackAgent
from src.apply.generic import GenericAdapter


class FakePage:
    def __init__(self, html: str):
        self._html = html

    async def content(self):
        return self._html


def test_generic_adapter_matches_non_ats_form():
    adapter = GenericAdapter()

    assert adapter.matches("https://example.com/careers/application")
    assert not adapter.matches("https://jobs.lever.co/example/123")


def test_generic_adapter_extracts_and_fill_logic():
    html = """
    <html><body>
      <form>
        <label for="full_name">Full Name</label>
        <input id="full_name" name="full_name" type="text">

        <label for="experience">Experience</label>
        <textarea id="experience" name="experience"></textarea>
      </form>
    </body></html>
    """
    adapter = GenericAdapter()
    fields = asyncio.run(adapter.extract_fields(FakePage(html)))
    names = {field["name"] for field in fields}

    assert "full_name" in names
    assert "experience" in names
    assert any(field["type"] == "textarea" and field["name"] == "experience" for field in fields)


def test_browser_use_fallback_agent_stops_before_submit():
    agent = BrowserUseFallbackAgent()

    assert agent.enabled is False
    assert agent.can_run() is True
    assert agent.should_submit is False
