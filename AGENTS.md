# AGENTS.md - Agent Roles & System Specification

This document defines agent instructions and system boundaries for autonomous agents, coding assistants (OpenAI Codex, ChatGPT, Cursor, Copilot, Antigravity, Claude Code), and human contributors.

---

## Onboarding & everyday use (read first)

When the user wants to get started, set up, "use this repo", or find jobs, follow [`docs/ONBOARDING_PLAYBOOK.md`](docs/ONBOARDING_PLAYBOOK.md).

- **Run every command yourself and show the results in chat. Ask the user's questions in chat.** Never tell the user to run commands in their terminal.
- **Never run `python -m src.cli setup`.** It is an interactive terminal wizard and will hang. Use the non-interactive `python -m src.cli onboard ...` commands.
- Start with `.venv/bin/python -m src.cli onboard status --json` (Windows: `.venv\Scripts\python.exe`); create `.venv` first if it is missing. Its `next_step` says what to do next.

---

## Agent Role: Onboarding & Operations Assistant

### Purpose & Scope
The Onboarding & Operations Assistant guides new users through setting up the repository, configuring their target roles and locations, explaining API keys, ensuring local database isolation, and executing discovery runs safely.

### Primary Commands
```bash
python -m src.cli onboard status --json  # Onboarding state + next step (agents: see playbook)
python -m src.cli setup              # Interactive wizard (humans in a terminal only)
python -m src.cli discover           # Multi-tier job discovery
python -m src.cli sync-notion        # Sync to Notion table
python -m src.cli reset-db           # Clean slate database reset
python -m src.cli verify-secrets     # Audit repository for exposed secrets
```

### Architecture Breakdown
1. **Tier 1 (Direct ATS APIs):** Greenhouse, Lever, Ashby, SmartRecruiters direct JSON polling. Free, no API keys.
2. **Tier 2 (JobSpy Aggregators):** LinkedIn, Indeed, Glassdoor, Naukri without browser overhead. Free, no API keys.
3. **Tier 3 (Apify Naukri):** Cloud actor for anti-bot & residential proxy bypass. Fallback only when JobSpy returns 0 Naukri jobs. Optional `APIFY_API_TOKEN`.
4. **Tier 4 (Firecrawl Enterprise):** Client-side SPA extraction for ~20 enterprise career portals (budget-capped). Optional `FIRECRAWL_API_KEY`.
5. **Local SQLite Ledger (`data/jobs.db`):** Local deduplication ledger with strict `UNIQUE(url)` constraint.
6. **Notion Database Sync:** Interactive tabular tracking board with direct application links.

### Critical Safety Invariants
1. **NO SECRETS IN GIT:** Secrets must NEVER be written to `config.yaml`, python source files, or markdown documentation. All secrets live strictly in `.env`.
2. **NO DATABASE COMMITS:** `data/jobs.db` is strictly local and must remain in `.gitignore`.
3. **PRE-PUSH AUDIT:** Run `python -m src.cli verify-secrets` before every commit or pull request.
