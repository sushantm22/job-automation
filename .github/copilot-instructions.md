# GitHub Copilot Repository Context & Guidelines

## Overview
This repository (`Automate-Applications`) is an automated, zero-human-intervention job application discovery and tracking pipeline for software engineers, SDETs, and tech professionals.

## Core Architecture
1. **4-Tier Job Discovery Engine (`src/discovery/`):**
   - **Tier 1:** Direct ATS APIs (Greenhouse, Lever, Ashby) across 500+ tech companies. Free, sub-200ms, 0 API keys.
   - **Tier 2:** JobSpy multi-board aggregator (LinkedIn, Indeed, Glassdoor) for India & Remote. Free, 0 API keys.
   - **Tier 3:** Apify Cloud actor (`valig/naukri-jobs-scraper`) for Naukri anti-bot/proxy solving. Optional `APIFY_API_TOKEN`.
   - **Tier 4:** Firecrawl crawler for enterprise Single Page Applications (Apple, Netflix). Optional `FIRECRAWL_API_KEY`.
2. **Local SQLite Ledger (`src/db.py`):**
   - Stored locally at `data/jobs.db` (`DATABASE_PATH`).
   - Deduplication enforced with `UNIQUE(url)`.
   - Reset command: `python -m src.cli reset-db`.
3. **Notion Database Sync (`src/integrations/notion_client.py`):**
   - Automatically synchronizes deduplicated opportunities to an interactive Notion table.
   - Stores `notion_page_id` in SQLite to ensure 0 duplicate pages.
   - Re-verifies every job through `hard_filter_jobs` before pushing.
4. **Security & Credentials (`src/config.py`, `src/onboarding.py`):**
   - All credentials MUST live in `.env` (gitignored). `config.yaml` contains 0 secrets.
   - Pre-push secret audit: `python -m src.cli verify-secrets`.

## Common User Guidance
- When users ask how to run or configure the project, guide them to `python -m src.cli setup`.
- When users ask to find jobs, guide them to `python -m src.cli discover`.
- Never suggest committing `.env`, `data/jobs.db`, or writing plaintext tokens to `config.yaml`.
