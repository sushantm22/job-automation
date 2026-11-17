# 🚀 Quickstart Guide: Job Application Automation

Welcome! This system automates job opportunity discovery across 4 resilient tiers (Direct ATS APIs, JobSpy Aggregators, Apify Naukri, and Firecrawl Enterprise Portals), deduplicates them into your personal local database, and syncs them directly to an interactive Notion dashboard.

---

## ⚡ Easiest Setup: Let Your AI Assistant Do It (Recommended)

1. Get the code:
   ```bash
   git clone https://github.com/sushantm22/job-automation.git
   ```
2. Open the folder in an AI coding assistant that can run commands: **Claude Code, Cursor, OpenAI Codex,
   GitHub Copilot (agent mode) or Gemini CLI**.
3. Type: **"Set me up"**

The assistant installs everything, asks you a few questions **in the chat** (which roles, which
locations, optional Notion tracking and keys), runs your first job search, and shows you the matches.
You don't need to type any commands. Afterwards, just ask it things like *"find new jobs"* or *"show my
jobs"*.

> Using ChatGPT/Claude/Gemini **on the web**? Those can't run commands on your computer. See
> [docs/UNIVERSAL_AGENT_PROMPT.md](docs/UNIVERSAL_AGENT_PROMPT.md).

---

## 🖥️ Alternative: Set Up Yourself in a Terminal

```bash
git clone https://github.com/sushantm22/job-automation.git
cd job-automation

# Python 3.10+: creates .venv, installs requirements, creates .env (Windows: py -3 bootstrap.py)
python3 bootstrap.py
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# Interactive wizard: roles, profile, optional keys, Notion table
python -m src.cli setup
```

Your choices are saved to gitignored files (`config.local.yaml`, `.env`, `data/profile.json`), so
nothing personal ever gets committed.

---

## 🔑 Which API Keys Do I Need?

| Service / Tier | Required? | Cost | Description |
| :--- | :---: | :---: | :--- |
| **Tier 1 (Direct ATS APIs)** | **No** | **100% Free** | Direct JSON endpoints for Greenhouse, Lever, Ashby and SmartRecruiters across 150+ companies, plus live Keka/SuccessFactors career sites and the free JobHive dataset (Workday, Oracle, SuccessFactors, Darwinbox, Keka, iCIMS); jobs that close are marked Closed. **Zero API keys needed!** |
| **Tier 2 (JobSpy Aggregators)** | **No** | **100% Free** | Scrapes LinkedIn, Indeed, and Glassdoor without browser overhead. **Zero API keys needed!** |
| **Google Gemini API** | Not used yet | Free Tier | Planned for job-match scoring and resume tailoring. Not needed today. |
| **Tier 3 (Apify Naukri)** | Optional | Free (\$5/mo) | Solves Cloudflare & residential proxies for Naukri. [Get free token here](https://console.apify.com/account/integrations). |
| **Tier 4 (Firecrawl)** | Optional | Free (500 credits) | AI crawler for custom JavaScript portals (Google, Apple, Netflix). [Get free key here](https://firecrawl.dev/). |
| **Notion Integration** | Optional | Free | Syncs discovered jobs into an interactive Notion board. [Get internal integration token](https://www.notion.so/my-integrations). |

> [!TIP]
> **You can start immediately with ZERO API keys!** Tiers 1 and 2 will discover hundreds of jobs out of the box.

---

## 🔍 Daily Commands

### 1. Discover New Jobs
```bash
# Run all active tiers with automatic deduplication & Notion sync
python -m src.cli discover

# Run only specific tiers (e.g. free Tier 1 and Tier 2)
python -m src.cli discover --tiers 1,2

# Set company limit
python -m src.cli discover --company-limit 20
```

### 2. Sync Existing SQLite Records to Notion
```bash
python -m src.cli sync-notion            # pushes every job not yet in Notion
```

### 3. Reset Your Local Database to a Clean Slate
If you ever want to clear your local database and start completely fresh:
```bash
python -m src.cli reset-db
```

### 4. Verify No Secrets Are Exposed Before Git Push
Before pushing any code to GitHub, run the security audit:
```bash
python -m src.cli verify-secrets
```

---

## 🔒 Security & Data Privacy

* **Your API tokens are NEVER committed to GitHub:** Keys live exclusively in your local `.env` file, which is blocked by `.gitignore`.
* **Personal Database Isolation:** All scraped jobs are stored in your personal local SQLite database (`data/jobs.db`). No one else's jobs will ever enter your database or Notion workspace.
* For more details, see [docs/CREDENTIALS_AND_SECURITY.md](docs/CREDENTIALS_AND_SECURITY.md).
