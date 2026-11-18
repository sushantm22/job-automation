# CLAUDE.md - Instructions for Claude Code & Anthropic Agents

## Project Overview
`Automate-Applications` is an automated, zero-human-intervention job discovery, deduplication, scoring, and application tracking platform for **any role, technical or business** (Sales Manager, Marketing, HR, Finance, SDET, ...) in **India and Remote**. Each user sets their own roles during onboarding; they are saved in `config.local.yaml` (gitignored) and nothing is shipped as a default.

> **Comprehensive Knowledge Transfer:** For full historical context, solved issues, and roadmap details, read [`docs/KNOWLEDGE_TRANSFER.md`](docs/KNOWLEDGE_TRANSFER.md).

---

## Onboarding & Everyday Use (read first)

When the user wants to get started, set up, "use this repo", or find jobs, follow **[`docs/ONBOARDING_PLAYBOOK.md`](docs/ONBOARDING_PLAYBOOK.md)** (also available as the `/onboard` skill).

- **Run every command yourself and show the results in chat. Ask the user's questions in chat.** Never tell the user to run commands in their terminal.
- **Never run `python -m src.cli setup`.** It is an interactive terminal wizard and will hang. Use the non-interactive `python -m src.cli onboard ...` commands.
- **Read the whole playbook before running anything**, then follow it step by step. Don't improvise the setup.
- **First command, in one call:** `cd "<project folder>" && python3 bootstrap.py` (Windows: `py -3 bootstrap.py`). It creates `.venv`, installs requirements, creates `.env` and prints `onboard status --json`; its `next_step` says what to do next. Afterwards always use `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`), never `source .venv/bin/activate`.
- **Combine commands with `&&` and skip exploratory commands**: the user may have to approve every call.
- **Secrets are piped, never typed:** `printf '%s' "$KEY" | .venv/bin/python -m src.cli onboard set-key NAME`, or the user edits `.env` and you run `onboard check-keys`.
- **Never write `.env`, `config.local.yaml` or `data/profile.json` by hand or with placeholder values.** Only the `onboard` commands write them, with values the user gave you.

---

## 4-Tier Discovery Architecture

1. **Tier 1 (Direct ATS APIs):** Direct JSON endpoints for Greenhouse, Lever, Ashby and SmartRecruiters across 150+ companies in `src/discovery/companies.yaml` (new entries are added to each user's registry automatically). **100% Free, instant (<200ms), zero API keys.** Tier 1 also reads the free **JobHive** dataset (`storage.stapply.ai/jobs/v1`, 16 ATS sources: Workday, Oracle, SuccessFactors, iCIMS, Darwinbox, Keka, Phenom, Amazon, Eightfold, Zoho Recruit, company-wide Greenhouse/Lever/Ashby/SmartRecruiters and more; India rows by `country_iso` or place name, column-level HTTP range reads with retries, cached by Last-Modified), since Workday blocks direct non-browser access. Jobs that disappear from a complete daily snapshot are marked **closed** (DB `closed_at`; Notion New/Reviewing → Closed, never overwriting Applied/Interview). **Keka and SuccessFactors** are scraped live via the `ats-scrapers` package (core install only, never its `[scrapers]`/`[all]` extras, which add browser-impersonation tools).
2. **Tier 2 (JobSpy Aggregator):** Scrapes 4 sources (LinkedIn, Indeed, Glassdoor, Naukri) for India & Remote: one India search per role, up to 100 results per site (`discovery.jobspy`). The first search for a set of roles looks back `search.max_job_age_days`; later runs only look back to the last completed run (`{db}.jobspy-state.json`). LinkedIn runs paced and waits a minute on HTTP 429 (no proxies or evasion). **100% Free, zero API keys.**
3. **Tier 3 (Apify Naukri Anti-Bot):** Cloud residential proxy actor (`valig/naukri-jobs-scraper`). **Smart Fallback:** Only fires if Tier 2 (JobSpy) returned 0 Naukri results, conserving free credits. Optional `APIFY_API_TOKEN` in `.env`.
4. **Tier 4 (Firecrawl Enterprise Portals):** Dynamic client-side SPA crawler for 20 custom portals (Google, Apple, Microsoft, Amazon, Meta, Swiggy, Flipkart, etc.). **Smart Fallback:** Skips companies already found in Tiers 1-2. Enforces `firecrawl_daily_budget: 10` to conserve credits. Optional `FIRECRAWL_API_KEY` in `.env`.

---

## Key CLI Commands

```bash
# Onboarding (non-interactive; for assistants and scripts)
python3 bootstrap.py                             # Step 0 in one command: venv, requirements, onboard prepare, status
python -m src.cli onboard prepare                # Step 0: create .env (from .env.example), database, company list
python -m src.cli onboard status --json          # What's done/missing + next_step
python -m src.cli onboard check-keys             # Verify keys the user added to .env (never prints values)
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
python -m src.cli sync-notion        # Push ALL pending jobs to Notion (discover pushes max 200/run)
python -m src.cli prune-old          # Close jobs past their age limit (30d job boards / 60d company sites) + old undated backlog

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
- `src/discovery/greenhouse.py`, `lever.py`, `ashby.py`, `smartrecruiters.py`: Tier 1 direct ATS API adapters (SmartRecruiters is filtered to India server-side).
- `src/discovery/jobhive.py`: Tier 1 reader for the public JobHive dataset (file URLs from its manifest; Workday has no posting dates; third-party free service: 5xx/timeouts retried, other failures skipped; feeds closed-job tracking).
- `src/discovery/freshness.py`: Age limits (`search.max_job_age_days`, default 30, for job boards; `search.max_company_job_age_days`, default 60, for company career sites, whose listings are still open) and first-seen tracking for undated listings (`search.undated_jobs: first_seen|include`, table `seen_listings`).
- `src/discovery/ats_scrapers_adapter.py`: Tier 1 live Keka/SuccessFactors via `ats-scrapers`; refuses any scraper that uses impersonation.
- `src/discovery/jobspy_adapter.py`: Tier 2 JobSpy adapter (LinkedIn, Indeed, Glassdoor, Naukri; Google Jobs disabled: it requires JavaScript since Jan 2025).
- `src/discovery/apify_adapter.py`: Tier 3 Apify cloud anti-bot actor for Naukri.
- `src/discovery/firecrawl_adapter.py`: Tier 4 Firecrawl dynamic client-side SPA crawler.
- `src/discovery/registry.py`, `harvester.py`: Company board registry (SQLite), auto-harvesting, and `companies.yaml` sync.
- `src/discovery/companies.yaml`: 140+ ATS company slugs + 20 custom enterprise portals.
- `src/integrations/notion_client.py`: Notion API database client with table formatting & duplicate guardrails.
- `src/scoring.py`: `related_title_candidates` suggests close titles from the job boards (shown after `discover`). Role-agnostic title matching (`title_matches_roles`: whole words, seniority ignored, abbreviations like BDM/KAM/Sr/Mgr, "Manager - Sales" and "Head of Sales" orderings; titles only, never descriptions) and foreign-exclusion geo-filtering (`hard_filter_jobs`).
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
3. **Resume Tailoring:** Implement real tailoring in `src/tailoring.py` to highlight the skills that match each job posting.
