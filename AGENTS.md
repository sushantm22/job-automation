# AGENTS.md - Agent Roles & System Specification

This document defines agent instructions and system boundaries for autonomous agents, coding assistants (OpenAI Codex, ChatGPT, Cursor, Copilot, Antigravity, Claude Code), and human contributors.

---

## Agent Role: Onboarding & Operations Assistant

### Purpose & Scope
The Onboarding & Operations Assistant guides new users through setting up the repository, configuring their target roles and locations, explaining API keys, ensuring local database isolation, and executing discovery runs safely.

### Primary Commands
```bash
python -m src.cli setup              # Interactive setup wizard
python -m src.cli discover           # Multi-tier job discovery
python -m src.cli sync-notion        # Sync to Notion table
python -m src.cli reset-db           # Clean slate database reset
python -m src.cli verify-secrets     # Audit repository for exposed secrets
```

### Architecture Breakdown
1. **Tier 1 (Direct ATS APIs):** Greenhouse, Lever, Ashby direct JSON polling. Free, no API keys.
2. **Tier 2 (JobSpy Aggregators):** LinkedIn, Indeed, Glassdoor without browser overhead. Free, no API keys.
3. **Tier 3 (Apify Naukri):** Cloud actor for anti-bot & residential proxy bypass. Optional `APIFY_API_TOKEN`.
4. **Tier 4 (Firecrawl Enterprise):** Client-side SPA extraction for Apple and Netflix. Optional `FIRECRAWL_API_KEY`.
5. **Local SQLite Ledger (`data/jobs.db`):** Local deduplication ledger with strict `UNIQUE(url)` constraint.
6. **Notion Database Sync:** Interactive tabular tracking board with direct application links.

### Critical Safety Invariants
1. **NO SECRETS IN GIT:** Secrets must NEVER be written to `config.yaml`, python source files, or markdown documentation. All secrets live strictly in `.env`.
2. **NO DATABASE COMMITS:** `data/jobs.db` is strictly local and must remain in `.gitignore`.
3. **PRE-PUSH AUDIT:** Run `python -m src.cli verify-secrets` before every commit or pull request.
