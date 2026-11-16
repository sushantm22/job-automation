# CLAUDE.md - Instructions for Claude Code & Anthropic Agents

## Project Overview
`Automate-Applications` is an automated, zero-human-intervention job discovery, deduplication, scoring, and application tracking platform for senior tech roles (SDET Lead, Senior SDET, QA Automation, Engineering in Test) in **India and Remote**.

> **Comprehensive Knowledge Transfer:** For full historical context, solved issues, and roadmap details, read [`docs/KNOWLEDGE_TRANSFER.md`](docs/KNOWLEDGE_TRANSFER.md).

---

## Onboarding & Everyday Use (read first)

When the user wants to get started, set up, "use this repo", or find jobs, follow **[`docs/ONBOARDING_PLAYBOOK.md`](docs/ONBOARDING_PLAYBOOK.md)** (also available as the `/onboard` skill).

- **Run every command yourself and show the results in chat. Ask the user's questions in chat.** Never tell the user to run commands in their terminal.
- **Never run `python -m src.cli setup`.** It is an interactive terminal wizard and will hang. Use the non-interactive `python -m src.cli onboard ...` commands.
- Start with `.venv/bin/python -m src.cli onboard status --json` (create `.venv` first if it is missing; see the playbook). Its `next_step` says what to do next.

---

## 4-Tier Discovery Architecture

1. **Tier 1 (Direct ATS APIs):** Direct JSON endpoints for Greenhouse, Lever, and Ashby across 140+ tech companies in `src/discovery/companies.yaml` (loaded into the registry automatically on first run). **100% Free, instant (<200ms), zero API keys.**
2. **Tier 2 (JobSpy Aggregator):** Scrapes 5 sources (LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri) for India & Remote. **100% Free, zero API keys.**
3. **Tier 3 (Apify Naukri Anti-Bot):** Cloud residential proxy actor (`valig/naukri-jobs-scraper`). **Smart Fallback:** Only fires if Tier 2 (JobSpy) returned 0 Naukri results, conserving free credits. Optional `APIFY_API_TOKEN` in `.env`.
4. **Tier 4 (Firecrawl Enterprise Portals):** Dynamic client-side SPA crawler for 20 custom portals (Google, Apple, Microsoft, Amazon, Meta, Swiggy, Flipkart, etc.). **Smart Fallback:** Skips companies already found in Tiers 1-2. Enforces `firecrawl_daily_budget: 10` to conserve credits. Optional `FIRECRAWL_API_KEY` in `.env`.

---

## Key CLI Commands

```bash
# Onboarding (non-interactive; for assistants and scripts)
python -m src.cli onboard status --json          # What's done/missing + next_step
python -m src.cli onboard set-search --roles "..." --locations "..."   # Saved to config.local.yaml (gitignored)
printf '%s' "$KEY" | python -m src.cli onboard set-key NOTION_API_KEY   # Secret via stdin -> .env
python -m src.cli onboard set-profile first_name=... city=... resume=/path/cv.pdf
python -m src.cli onboard skip api_keys|notion|profile
python -m src.cli setup                          # Interactive wizard for humans in a terminal (NOT for agents)

# Discovery & Scraping
python -m src.cli discover           # Run all active tiers with deduplication & Notion sync
python -m src.cli discover --tiers 1,2 # Run free tiers only (Greenhouse/Lever/Ashby + JobSpy)
python -m src.cli discover --company-limit 20 # Custom company limit (rotates through the registry)

# Notion Sync & Management
python -m src.cli init-notion-db --parent-page-id <url>  # Create Notion table; saves NOTION_DATABASE_ID to .env
python -m src.cli sync-notion        # Sync pending SQLite jobs to Notion

# Security & Database Maintenance
python -m src.cli verify-secrets     # Audit tracked files for exposed API keys (MUST run before push)
python -m src.cli reset-db --yes     # Reset local database (confirm with the user in chat first)
python -m src.cli list               # List stored jobs from SQLite

# Testing
PYTHONPATH=. .venv/bin/pytest -v     # Run full automated test suite
```

---

## Code Map

- `src/discovery/engine.py`: Coordinates all 4 tiers, smart fallbacks, auto-harvesting, and deduplication.
- `src/discovery/greenhouse.py`, `lever.py`, `ashby.py`: Tier 1 direct ATS API adapters.
- `src/discovery/jobspy_adapter.py`: Tier 2 JobSpy adapter (LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri).
- `src/discovery/apify_adapter.py`: Tier 3 Apify cloud anti-bot actor for Naukri.
- `src/discovery/firecrawl_adapter.py`: Tier 4 Firecrawl dynamic client-side SPA crawler.
- `src/discovery/registry.py`, `harvester.py`: Company board registry (SQLite), auto-harvesting, and `companies.yaml` sync.
- `src/discovery/companies.yaml`: 140+ ATS company slugs + 20 custom enterprise portals.
- `src/integrations/notion_client.py`: Notion API database client with table formatting & duplicate guardrails.
- `src/scoring.py`: Strict role title matching and foreign-exclusion geo-filtering (`hard_filter_jobs`).
- `src/config.py`: Pydantic settings from `config.yaml`, overridden by `config.local.yaml` (gitignored) and `.env` (`firecrawl_daily_budget: 10`).
- `src/onboard_steps.py`: Non-interactive onboarding steps behind the `onboard ...` commands.
- `src/onboarding.py`: Interactive setup wizard, `.env` helpers, and pre-commit secret scanner.
- `src/db.py`: SQLite schema, upsert, and isolation ledger (`DATABASE_PATH`, default `data/jobs.db`).
- `src/apply/`: ATS application form extraction and filling adapters plus the review gate (`review.py`) (Stage 2).
- `src/answer_bank.py`, `src/answer_resolution.py`: Answer bank and form-field resolution from the candidate profile (Stage 2).

---

## Security & Database Invariants (NEVER VIOLATE)

1. **NEVER write secrets to git-tracked files:** `config.yaml` must only contain empty placeholders `""` for credentials. All actual API keys (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `FIRECRAWL_API_KEY`, `GEMINI_API_KEY`) must reside strictly in `.env`.
2. **NEVER commit personal data:** `.env`, `config.local.yaml`, `data/jobs.db`, `data/profile.json`, `data/candidate_answers_reference.json`, and resumes are blocked in `.gitignore`. The SQLite database is private to each developer.
3. **ALWAYS run `verify-secrets` before git commits:** Guarantees zero credential leaks.
4. **FILTER PRECISION:** All jobs must pass through `hard_filter_jobs` in `src/scoring.py` to ensure only target-role India or Remote jobs reach SQLite and Notion.

---

## Next Development Priorities (Stage 2)
1. **Form Filling & Application Automation:** Test and wire `src/apply/` adapters (Greenhouse, Lever, Ashby) with `src/answer_bank.py` and `src/answer_resolution.py` in dry-run review mode.
2. **Browser-Use Fallback Agent:** Enhance `src/apply/fallback_agent.py` for custom application portals.
3. **Resume Tailoring:** Implement real tailoring in `src/tailoring.py` to highlight matching SDET skills per job posting.
