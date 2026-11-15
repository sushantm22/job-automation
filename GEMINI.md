# GEMINI.md - Instructions for Gemini CLI & Google Antigravity

## Workspace Overview
You are working in `Automate-Applications`, an automated 4-tier job discovery and application tracking platform with Notion tabular synchronization and local SQLite deduplication.

## Essential Commands
- **Interactive Setup:** `python -m src.cli setup`
- **Multi-Tier Discovery:** `python -m src.cli discover` (or `python -m src.cli discover --tiers 1,2` for 100% free tiers)
- **Notion Sync:** `python -m src.cli sync-notion`
- **Reset Local DB:** `python -m src.cli reset-db`
- **Security Check:** `python -m src.cli verify-secrets`
- **Unit Tests:** `PYTHONPATH=. .venv/bin/pytest -v`

## Core Guidelines
1. **Security & Secrets:** All API keys (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `FIRECRAWL_API_KEY`, `GEMINI_API_KEY`) belong strictly in `.env`. Never write keys to `config.yaml` or tracked git files.
2. **Local Isolation:** `data/jobs.db` is private and unique to the current user. Never commit `data/jobs.db` or `.env`.
3. **Filtering Precision:** All jobs flow through `src/scoring.py` (`hard_filter_jobs`) which strictly enforces target role titles and Indian/Remote locations.
