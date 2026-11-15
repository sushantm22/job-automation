from __future__ import annotations

import re
from pathlib import Path
from src.onboarding import audit_tracked_secrets, mask_secret

ROOT = Path(__file__).resolve().parent.parent


def test_tracked_files_contain_zero_secrets():
    """Verifies that no API keys or secret patterns exist in git-tracked files."""
    violations = audit_tracked_secrets()
    assert violations == [], f"Found exposed credentials in git: {violations}"


def test_gitignore_blocks_critical_files():
    """Verifies that .gitignore blocks .env and database files."""
    gitignore_path = ROOT / ".gitignore"
    assert gitignore_path.exists()
    content = gitignore_path.read_text(encoding="utf-8")
    
    # Assert critical entries are ignored
    assert ".env" in content
    assert "*.db" in content or "data/jobs.db" in content


def test_mask_secret_helper():
    """Verifies that sensitive keys are masked with asterisks."""
    assert mask_secret("ntn_1234567890abcdef1234567890") == "ntn_...7890"
    assert mask_secret("fc-1234567890abcdef123456") == "fc-1...3456"
    assert mask_secret("short") == "********"
    assert "None" in mask_secret("")
