# CLAUDE.md - Instructions for Claude Code & Anthropic Agents

## Project Overview
`Automate-Applications` is an automated, zero-human-intervention job discovery, deduplication, scoring, and application tracking platform for senior tech roles (SDET Lead, Senior SDET, QA Automation, Engineering in Test) in **India and Remote**.

> **Comprehensive Knowledge Transfer:** For full historical context, solved issues, and roadmap details, read [`docs/KNOWLEDGE_TRANSFER.md`](file:///Users/sushantmishra/AI/projects/manasvee%20job%20ai%20apply/Automate-Applications/docs/KNOWLEDGE_TRANSFER.md).

---

## 4-Tier Discovery Architecture

1. **Tier 1 (Direct ATS APIs):** Direct JSON endpoints for Greenhouse, Lever, and Ashby across 140+ tech companies in `src/discovery/companies.yaml`. **100% Free, instant (<200ms), zero API keys.**
2. **Tier 2 (JobSpy Aggregator):** Scrapes 5 sources (LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri) for India & Remote. **100% Free, zero API keys.**
3. **Tier 3 (Apify Naukri Anti-Bot):** Cloud residential proxy actor (`valig/naukri-jobs-scraper`). **Smart Fallback:** Only fires if Tier 2 (JobSpy) returned 0 Naukri results, conserving free credits. Optional `APIFY_API_TOKEN` in `.env`.
4. **Tier 4 (Firecrawl Enterprise Portals):** Dynamic client-side SPA crawler for 20 custom portals (Google, Apple, Microsoft, Amazon, Meta, Swiggy, Flipkart, etc.). **Smart Fallback:** Skips companies already found in Tiers 1-2. Enforces `firecrawl_daily_budget: 10` to conserve credits. Optional `FIRECRAWL_API_KEY` in `.env`.

---

## Key CLI Commands

```bash
# Guided Onboarding & Setup
python -m src.cli setup              # Interactive setup wizard

# Discovery & Scraping
python -m src.cli discover           # Run all active tiers with deduplication & Notion sync
python -m src.cli discover --tiers 1,2 # Run free tiers only (Greenhouse/Lever/Ashby + JobSpy)
python -m src.cli discover --company-limit 20 # Custom company limit

# Notion Sync & Management
python -m src.cli init-notion-db     # Create new Notion table under parent page
python -m src.cli sync-notion        # Sync pending SQLite jobs to Notion

# Security & Database Maintenance
python -m src.cli verify-secrets     # Audit tracked files for exposed API keys (MUST run before push)
python -m src.cli reset-db           # Cleanly reset local database with confirmation prompt
python -m src.cli list               # List stored jobs from SQLite

# Testing
PYTHONPATH=. .venv/bin/pytest -v     # Run full automated test suite (63 unit tests)
```

---

## Code Map

- `src/discovery/engine.py`: Coordinates all 4 tiers, smart fallbacks, auto-harvesting, and deduplication.
- `src/discovery/jobspy_adapter.py`: Tier 2 JobSpy adapter (LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri).
- `src/discovery/apify_adapter.py`: Tier 3 Apify cloud anti-bot actor for Naukri.
- `src/discovery/firecrawl_adapter.py`: Tier 4 Firecrawl dynamic client-side SPA crawler.
- `src/discovery/companies.yaml`: 140+ ATS company slugs + 20 custom enterprise portals.
- `src/integrations/notion_client.py`: Notion API database client with table formatting & duplicate guardrails.
- `src/scoring.py`: Strict role title matching and foreign-exclusion geo-filtering (`hard_filter_jobs`).
- `src/config.py`: Pydantic settings loading from `.env` and `config.yaml` (`firecrawl_daily_budget: 10`).
- `src/onboarding.py`: Interactive setup wizard and pre-commit secret scanner.
- `src/db.py`: SQLite schema, upsert, and isolation ledger (`data/jobs.db`).
- `src/adapters/`: ATS application form extraction and automated filling adapters (Stage 2).
- `src/review/gate.py`: Human review approval gate before form submissions.

---

## Security & Database Invariants (NEVER VIOLATE)

1. **NEVER write secrets to git-tracked files:** `config.yaml` must only contain empty placeholders `""` for credentials. All actual API keys (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `FIRECRAWL_API_KEY`, `GEMINI_API_KEY`) must reside strictly in `.env`.
2. **NEVER commit `.env` or `data/jobs.db`:** Both are blocked in `.gitignore`. The SQLite database is private to each developer.
3. **ALWAYS run `verify-secrets` before git commits:** Guarantees zero credential leaks.
4. **FILTER PRECISION:** All jobs must pass through `hard_filter_jobs` in `src/scoring.py` to ensure only SDET/QA India or Remote roles reach SQLite and Notion.

---

## Next Development Priorities (Stage 2)
1. **Form Filling & Application Automation:** Test and wire `src/adapters/` (Greenhouse, Lever, Ashby) with `src/matching/answer_bank.py` in dry-run review mode.
2. **Browser-Use Fallback Agent:** Enhance `src/adapters/browser_use_fallback.py` for custom application portals.
3. **Resume Tailoring:** Implement `src/tailoring/resume.py` to highlight matching SDET skills per job posting.
