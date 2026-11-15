# 🚀 Quickstart Guide: Job Application Automation

Welcome! This system automates job opportunity discovery across 4 resilient tiers (Direct ATS APIs, JobSpy Aggregators, Apify Naukri, and Firecrawl Enterprise Portals), deduplicates them into your personal local database, and syncs them directly to an interactive Notion dashboard.

---

## ⚡ 3-Minute Setup

### 1. Clone & Set Up Python Environment
```bash
# 1. Clone repository
git clone <your-repo-url>
cd Automate-Applications

# 2. Create and activate a Python 3.10+ virtual environment
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

### 2. Run the Interactive Setup Wizard
Run the onboarding agent to configure your target job roles, locations, and credentials:

```bash
python -m src.cli setup
```

The interactive wizard will:
1. Ask for your target job titles (e.g. *SDET, QA Automation, Backend Engineer*).
2. Ask for your preferred locations (*India, Remote, Bengaluru, Pune, etc.*).
3. Safely configure your API keys in your local `.env` file (which is strictly gitignored).
4. Connect to Notion and automatically provision your personal **Notion Job Opportunities** table.

---

## 🔑 Which API Keys Do I Need?

| Service / Tier | Required? | Cost | Description |
| :--- | :---: | :---: | :--- |
| **Tier 1 (Direct ATS APIs)** | **No** | **100% Free** | Direct JSON endpoints for Greenhouse, Lever, and Ashby across 500+ tech companies. **Zero API keys needed!** |
| **Tier 2 (JobSpy Aggregators)** | **No** | **100% Free** | Scrapes LinkedIn, Indeed, and Glassdoor without browser overhead. **Zero API keys needed!** |
| **Google Gemini API** | Recommended | Free Tier | Used for evaluating job match relevance and resume tailoring. [Get free key here](https://aistudio.google.com/). |
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
python -m src.cli sync-notion --limit 50
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
