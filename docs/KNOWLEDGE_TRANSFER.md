# Knowledge Transfer & Project Context: Automate-Applications

**Document Version:** 1.0  
**Target Audience:** Claude Code, AI Coding Assistants (VS Code), Human Collaborators (Sushant, Manasvee)  
**Current Git Branch:** `feature/crawler`  
**Test Suite Status:** 63/63 Passed (`PYTHONPATH=. .venv/bin/pytest -v`)

---

## 1. Executive Summary & Purpose

`Automate-Applications` is an automated, zero-human-intervention job discovery, deduplication, scoring, and application tracking platform designed for senior tech roles in **India (Bengaluru, Hyderabad, Pune, Mumbai, Gurgaon, Noida, Chennai, Delhi) and Remote**.

### Primary Target Candidate Profile
- **Target Roles:** Set per user during onboarding (saved in the gitignored `config.local.yaml`); no roles are shipped as defaults. The platform works for any role, technical or business (the original user's roles were SDET Lead, Senior SDET, QA Automation Engineer, QA Lead).
- **Exclusions:** Whatever the user adds to `exclude_keywords` (by default internships and unpaid roles). Jobs are matched on the title only, with seniority ignored, so users who don't want a level exclude it explicitly.
- **Locations:** India & Worldwide/India-eligible Remote. Foreign-only locations (US, UK, Canada, Europe) are strictly filtered out.

---

## 2. Architecture Breakdown

```
                         ┌────────────────────────────────────────────────────────┐
                         │               DISCOVERY SOURCES                        │
                         └────────────────────────────────────────────────────────┘
                                     │                        │               │
                ┌────────────────────┴───────────┐            │               └────────────────────────┐
                ▼                                ▼            ▼                                        ▼
     [ Tier 1: Direct APIs ]           [ Tier 2: JobSpy ]   [ Tier 3: Apify ]              [ Tier 4: Firecrawl ]
        Greenhouse / Lever / Ashby        LinkedIn / Indeed    Naukri & Protected Sites       20+ Enterprise Portals
      • 100% Free & Fast (<200ms)         Glassdoor / Google   • Smart Fallback: ONLY fires   • Smart Fallback: ONLY fires
      • 140+ tracked tech companies     • 100% Free, Python      if JobSpy returns 0 Naukri     for uncovered companies
      • Polled directly via JSON        • Pan-India & Remote   • Cloud anti-bot & CAPTCHA     • 10 credit daily budget cap
                │                                │            │                                        │
                └────────────────────────────────┼────────────┴────────────────────────────────────────┘
                                                 │
                                                 ▼
                                     [ Scoring & Geo-Filter ]
                                        (hard_filter_jobs)
                                                 │
                                                 ▼
                                     [ SQLite Deduplication Ledger ]
                                          (`data/jobs.db`)
                                                 │
                                                 ▼
                                     [ Notion Interactive Sync ]
```

### Tier 1: Direct ATS APIs (100% Free, Zero Keys)
- **Platforms:** Greenhouse, Lever, Ashby.
- **Endpoints:** Direct JSON polling (`boards-api.greenhouse.io`, `api.lever.co`, `api.ashbyhq.com`).
- **Registry:** 140+ tracked companies in `src/discovery/companies.yaml` and SQLite `company_registry`.
- **Performance:** Instant (<200ms per board), zero browser overhead, zero rate limits.

### Tier 2: JobSpy Multi-Aggregator (100% Free, Zero Keys)
- **Implemented in:** `src/discovery/jobspy_adapter.py`.
- **Sources (5 total):** LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri.
- **Configured For:** Pan-India metro hubs and targeted `is_remote=True` queries.

### Tier 3: Apify Cloud Anti-Bot (Smart Fallback for Naukri)
- **Implemented in:** `src/discovery/apify_adapter.py`.
- **Actor:** `valig/naukri-jobs-scraper` (residential proxies + CAPTCHA bypass).
- **Smart Fallback Rule:** Apify **ONLY** triggers if Tier 2 (JobSpy) returned 0 Naukri jobs. If JobSpy successfully fetched Naukri jobs, Tier 3 is skipped entirely, saving Apify free credits.
- **Token:** `APIFY_API_TOKEN` in `.env` ($5 monthly free credits).

### Tier 4: Firecrawl Enterprise Portals (Smart Fallback with Credit Budget)
- **Implemented in:** `src/discovery/firecrawl_adapter.py`.
- **Registry:** 20 enterprise companies loaded dynamically from `src/discovery/companies.yaml` (Google, Apple, Microsoft, Amazon, Meta, Flipkart, Swiggy, PhonePe, Razorpay, Zomato, CRED, Uber, Netflix, Walmart, Adobe, Salesforce, SAP, Atlassian, Spotify, PayPal).
- **Smart Fallback Rule:** Skips any company that already has jobs discovered via Tiers 1-2.
- **Credit Budget:** Enforces `firecrawl_daily_budget: 10` (max 10 scrape calls per run). On Firecrawl's free tier (500 credits), this guarantees **50 full discovery sessions**.
- **Token:** `FIRECRAWL_API_KEY` in `.env`.

### Automated Feedback Loop (Auto-Harvesting)
- When Tiers 2, 3, or 4 find job postings that link to a Greenhouse/Lever/Ashby board, `src/discovery/harvester.py` extracts the slug, validates the board, and automatically registers the company into SQLite and `companies.yaml` for Tier 1 polling in future runs.

### SQLite Ledger & Deduplication (`data/jobs.db`)
- Strict `UNIQUE(url)` constraint prevents any duplicate job insertions.
- Tracks `status` (`discovered`, `reviewed`, `applied`), `match_score`, and `notion_page_id`.
- Isolated locally via `DATABASE_PATH` env var.

### Notion Sync (`src/integrations/notion_client.py`)
- Syncs deduplicated jobs to an interactive Notion table with columns: Job Title, Company, Location, Match Score, Status, Direct URL, Discovered Date.
- Prevents duplicates by recording `notion_page_id` in SQLite and verifying every row through `hard_filter_jobs`.

---

## 3. History of Problems Solved & Decisions Made

| Problem Encountered | Root Cause | Solution Implemented |
|:---|:---|:---|
| **Local scrapers breaking on Naukri & SPAs** | Naukri uses Cloudflare/CAPTCHA; enterprise career sites (Apple, Netflix) use client-rendered JavaScript SPAs. | Integrated Apify residential proxy actors (Tier 3) and Firecrawl JS-rendering crawler (Tier 4). |
| **Apify & JobSpy redundancy on Naukri** | Both were scraping Naukri unconditionally, burning Apify credits unnecessarily. | Implemented **Smart Fallback**: Apify only executes if JobSpy returns 0 Naukri results. |
| **Firecrawl credit exhaustion on static portals** | Hardcoded 4 portals ran every time regardless of coverage, wasting free credits. | Replaced with dynamic 20-company list in `companies.yaml`, added `firecrawl_daily_budget: 10`, and skipped companies already found in Tiers 1-2. |
| **Legacy Database Pollution (1,900+ test jobs)** | A legacy test run on Nov 10-11 inserted hundreds of non-SDET, global, and test rows into SQLite and synced them to Notion. | 1) Purged SQLite down to 70 verified SDET/QA roles (backed up to `data/jobs.db.bak`).<br>2) Concurrently archived 1,469 legacy pages in Notion.<br>3) Added `hard_filter_jobs` directly inside `sync_jobs_to_notion`. |
| **Sensitive API Keys exposed in repo** | Live keys for Notion, Firecrawl, and Apify were present in `config.yaml`. | 1) Sanitized `config.yaml` to empty strings `""`.<br>2) Moved all tokens to `.env` (gitignored).<br>3) Built automated secret audit scanner: `python -m src.cli verify-secrets`. |
| **Apify scraper crash on nested dict payloads** | Apify returned dictionaries for `description` or `company` in some actor runs. | Updated `strip_html` in `src/discovery/base.py` and `parse_apify_naukri_items` to safely unpack dicts and lists. |

---

## 4. Current Repository State

```
Automate-Applications/
├── config.yaml                       # Application settings (0 secrets, budget=10)
├── .env                              # Local secrets: NOTION, APIFY, FIRECRAWL, GEMINI (gitignored)
├── .env.example                      # Safe template for new developers
├── data/
│   ├── jobs.db                       # Active SQLite ledger (70 clean SDET roles)
│   ├── jobs.db.bak                   # Safety backup of original database
│   └── seeds/companies_seed.json     # Initial seed list of tech companies
├── src/
│   ├── cli.py                        # Central CLI (setup, discover, sync-notion, reset-db, verify-secrets)
│   ├── config.py                     # Pydantic Settings with .env loading
│   ├── db.py                         # SQLite connection, migrations, upserts
│   ├── scoring.py                    # Strict title and geo-filtering (hard_filter_jobs)
│   ├── onboarding.py                 # Interactive onboarding wizard & secret scanner
│   ├── discovery/
│   │   ├── base.py                   # JobRecord model & HTML stripping utilities
│   │   ├── engine.py                 # 4-Tier Discovery Coordinator with smart fallbacks
│   │   ├── greenhouse.py             # Tier 1 Greenhouse API adapter
│   │   ├── lever.py                  # Tier 1 Lever API adapter
│   │   ├── ashby.py                  # Tier 1 Ashby API adapter
│   │   ├── jobspy_adapter.py         # Tier 2 JobSpy adapter (LinkedIn, Indeed, Glassdoor, Google, Naukri)
│   │   ├── apify_adapter.py          # Tier 3 Apify Cloud Actor adapter
│   │   ├── firecrawl_adapter.py      # Tier 4 Firecrawl dynamic portal scraper
│   │   ├── harvester.py              # Auto-harvesting regex & probe logic
│   │   ├── registry.py               # CompanyRegistry class
│   │   └── companies.yaml            # 140+ ATS slugs + 20 enterprise portals
│   ├── integrations/
│   │   └── notion_client.py          # Notion API integration
│   ├── adapters/                     # Form extraction & filling adapters (Stage 2)
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── generic.py
│   │   └── browser_use_fallback.py
│   ├── matching/                     # Profile & answer bank resolution (Stage 2)
│   ├── review/                       # Terminal review gate table (Stage 2)
│   └── tailoring/                    # Resume & cover letter tailoring (Stage 2)
├── tests/                            # 63 unit tests (100% passing)
├── CLAUDE.md                         # Native instructions for Claude Code CLI
├── AGENTS.md                         # Multi-agent specification (Codex, Cursor, etc.)
├── GEMINI.md                         # Antigravity & Gemini instructions
└── .github/
    ├── copilot-instructions.md       # Global Copilot instructions
    └── agents/
        └── setup-assistant.agent.md  # Copilot custom setup assistant agent
```

---

## 5. Essential CLI Commands Quick Reference

```bash
# 1. Onboarding & Verification
python -m src.cli setup              # Interactive setup wizard
python -m src.cli verify-secrets     # Audit repository for exposed secrets (MUST run before push)

# 2. Discovery Runs
python -m src.cli discover           # Full 4-tier discovery with smart fallbacks & Notion sync
python -m src.cli discover --tiers 1,2 # 100% free tiers only (zero API keys needed)
python -m src.cli discover --company-limit 25 # Limit Tier 1 company polling

# 3. Notion Sync
python -m src.cli sync-notion        # Sync pending SQLite jobs to Notion table
python -m src.cli init-notion-db     # Create a brand new Notion database table

# 4. Database Ledger
python -m src.cli list               # Inspect stored jobs in SQLite
python -m src.cli reset-db           # Wipe local database cleanly with safety confirmation

# 5. Testing
PYTHONPATH=. .venv/bin/pytest -v     # Run all 63 unit tests
```

---

## 6. Critical Security Invariants (NEVER VIOLATE)

1. **NO SECRETS IN GIT:** Never write API keys into `config.yaml`, python files, or markdown docs. All tokens live exclusively in `.env`.
2. **AUDIT BEFORE COMMITS:** Always run `python -m src.cli verify-secrets` before every git commit or PR.
3. **DATABASE IS PRIVATE:** `data/jobs.db` is strictly local to each developer. Never remove `data/jobs.db` or `.env` from `.gitignore`.

---

## 7. Stage 2 & Future Roadmap

When continuing development with Claude Code, here are the immediate next milestones:

1. **Stage 2: End-to-End Application Form Filling (Dry Run & Review Mode):**
   - Wire `src/orchestrator.py` with ATS form adapters (`greenhouse`, `lever`, `ashby`).
   - Connect `src/matching/answer_bank.py` and `profile_resolver.py` to auto-fill common candidate questions (notice period, current CTC, expected CTC, years of automation experience).
   - Test the terminal review gate (`src/review/gate.py`) to let the user approve or edit answers before submitting.
2. **Browser-Use Fallback Agent:**
   - Enhance `src/adapters/browser_use_fallback.py` using Playwright or BrowserBase for non-standard enterprise career portals.
3. **Resume Tailoring per Job Description:**
   - Implement `src/tailoring/resume.py` to highlight the user's skills that match each job posting (for example Selenium and Playwright for an SDET, or CRM and negotiation for a Sales Manager).
4. **Scheduled Automations:**
   - Add a cron job or scheduled automation to run `python -m src.cli discover` daily at 9:00 AM IST.
