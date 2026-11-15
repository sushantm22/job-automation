from src.apply.review import ReviewGate, render_review_table


class FakePage:
    def __init__(self, approved: bool = False):
        self.approved = approved
        self.submit_clicked = False

    async def click_submit(self):
        self.submit_clicked = True


def test_render_review_table_flags_low_confidence_answers():
    rows = render_review_table([
        {"label": "First Name", "value": "Manasvee", "source": "profile"},
        {"label": "Criminal History", "value": None, "source": "needs_human", "needs_human": True},
    ])

    assert rows[0]["source"] == "profile"
    assert rows[1]["needs_human"] is True


def test_review_gate_blocks_submit_in_dry_run_mode():
    gate = ReviewGate(dry_run=True)

    assert gate.should_submit("s") is False
    assert gate.should_submit("k") is False


def test_review_gate_allows_submit_after_approval():
    gate = ReviewGate(dry_run=False)

    assert gate.should_submit("s") is True
    assert gate.should_submit("k") is False


def test_submit_is_never_called_when_review_is_declined():
    page = FakePage(approved=False)
    gate = ReviewGate(dry_run=False)

    outcome = gate.apply_decision(page, "k")

    assert outcome is False
    assert page.submit_clicked is False
