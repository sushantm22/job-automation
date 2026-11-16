# GEMINI.md - Instructions for Gemini CLI & Google Antigravity

## Workspace Overview
You are working in `Automate-Applications`, an automated 4-tier job discovery and application tracking platform with Notion tabular synchronization and local SQLite deduplication.

## Onboarding & everyday use (read first)

When the user wants to get started, set up, "use this repo", or find jobs, follow [`docs/ONBOARDING_PLAYBOOK.md`](docs/ONBOARDING_PLAYBOOK.md).

- **Run every command yourself and show the results in chat. Ask the user's questions in chat.** Never tell the user to run commands in their terminal.
- **Never run `python -m src.cli setup`.** It is an interactive terminal wizard and will hang. Use the non-interactive `python -m src.cli onboard ...` commands.
- Start with `.venv/bin/python -m src.cli onboard status --json` (Windows: `.venv\Scripts\python.exe`); create `.venv` first if it is missing. Its `next_step` says what to do next.

## Essential Commands
- **Onboarding:** `python -m src.cli onboard status --json` (agents follow the playbook; never run the interactive `setup`)
- **Multi-Tier Discovery:** `python -m src.cli discover` (or `python -m src.cli discover --tiers 1,2` for 100% free tiers)
- **Notion Sync:** `python -m src.cli sync-notion`
- **Reset Local DB:** `python -m src.cli reset-db`
- **Security Check:** `python -m src.cli verify-secrets`
- **Unit Tests:** `PYTHONPATH=. .venv/bin/pytest -v`

## Core Guidelines
1. **Security & Secrets:** All API keys (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `FIRECRAWL_API_KEY`, `GEMINI_API_KEY`) belong strictly in `.env`. Never write keys to `config.yaml` or tracked git files.
2. **Local Isolation:** `data/jobs.db` is private and unique to the current user. Never commit `data/jobs.db` or `.env`.
3. **Filtering Precision:** All jobs flow through `src/scoring.py` (`hard_filter_jobs`) which strictly enforces target role titles and Indian/Remote locations.
