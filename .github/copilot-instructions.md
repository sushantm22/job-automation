# GitHub Copilot Repository Context & Guidelines

## Overview
This repository (`Automate-Applications`) is an automated, zero-human-intervention job application discovery and tracking pipeline for any role, technical or business, in India and Remote. Each user sets their own job titles during onboarding.

## Onboarding & everyday use (read first)

When the user wants to get started, set up, "use this repo", or find jobs, follow [`docs/ONBOARDING_PLAYBOOK.md`](docs/ONBOARDING_PLAYBOOK.md).

- **Run every command yourself and show the results in chat. Ask the user's questions in chat.** Never tell the user to run commands in their terminal.
- **Never run `python -m src.cli setup`.** It is an interactive terminal wizard and will hang. Use the non-interactive `python -m src.cli onboard ...` commands.
- **Read the whole playbook before running anything**, then follow it step by step. Don't improvise the setup.
- **First command, in one call:** `cd "<project folder>" && python3 bootstrap.py` (Windows: `py -3 bootstrap.py`). It creates `.venv`, installs requirements, creates `.env` and prints `onboard status --json`; its `next_step` says what to do next. Afterwards always use `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`), never `source .venv/bin/activate`.
- **Combine commands with `&&` and skip exploratory commands**: the user may have to approve every call.
- **Secrets are piped, never typed:** `printf '%s' "$KEY" | .venv/bin/python -m src.cli onboard set-key NAME`, or the user edits `.env` and you run `onboard check-keys`.
- **Never write `.env`, `config.local.yaml` or `data/profile.json` by hand or with placeholder values.** Only the `onboard` commands write them, with values the user gave you.

## Core Architecture
1. **4-Tier Job Discovery Engine (`src/discovery/`):**
   - **Tier 1:** Direct ATS APIs (Greenhouse, Lever, Ashby, SmartRecruiters) across 150+ companies, plus the free JobHive dataset (16 company ATS sources such as Workday, Oracle, SuccessFactors, Phenom, Amazon, with closed-job tracking) and live Keka/SuccessFactors via `ats-scrapers` (core install only). Free, sub-200ms, 0 API keys.
   - **Tier 2:** JobSpy multi-board aggregator (LinkedIn, Indeed, Glassdoor, Naukri) for India & Remote: 30 days and up to 100 results per site on the first search, then only since the last run. Free, 0 API keys.
   - **Tier 3:** Apify Cloud actor (`valig/naukri-jobs-scraper`) for Naukri anti-bot/proxy solving; fallback only when JobSpy returns 0 Naukri jobs. Optional `APIFY_API_TOKEN`.
   - **Tier 4:** Firecrawl crawler for ~20 enterprise career portals (budget-capped). Optional `FIRECRAWL_API_KEY`.
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
- In agent mode, set the project up for the user by following `docs/ONBOARDING_PLAYBOOK.md`: run the commands yourself and ask questions in chat.
- When users ask to find jobs, run `python -m src.cli discover --tiers 1,2` and show the matches (`python -m src.cli list`).
- Never end a reply by announcing a command ("I'm starting the search now") without running it in that same reply. `discover` and `sync-notion` take up to ~10 minutes: tell the user, then run them as a **normal terminal command, not a background one** (set isBackground=false). The tool then waits until the command finishes and returns all output in one step. Don't run them in the background and poll `get_terminal_output`: every check uses one of your ~25 tool calls per reply and stops the run with "Continue to iterate?". Don't post "still running" messages.
- **Always ask for the Notion page link in this chat** and wait for the reply; never reuse a link from an earlier conversation, memory or terminal history.
- After `discover`, if it prints "Close titles found", show the **whole numbered list** and ask which numbers to add as roles; never pick for the user.
- In chat-only mode (no terminal access), give one command at a time and ask the user to paste the output back.
- Never suggest committing `.env`, `data/jobs.db`, or writing plaintext tokens to `config.yaml`.
