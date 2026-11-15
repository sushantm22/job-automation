# 🔐 Credentials, Security & Multi-User Data Isolation

This document outlines the security architecture of the Job Application Automation system, details how API keys are handled, and explains how local database isolation prevents data leakage or cross-contamination between team members.

---

## 1. Zero-Credential Exposure (Git Safety)

### Where Credentials Live
* All API tokens, secrets, and private IDs live strictly in your local `.env` file.
* `config.yaml` contains **zero plaintext credentials**; it only contains general search keywords, timeouts, and tier feature toggles.
* `.gitignore` is configured to permanently ignore:
  ```gitignore
  .env
  .env.*
  !.env.example
  data/jobs.db
  *.db
  *.bak
  ```

### Automated Secret Scanning
The codebase includes an automated security audit scanner:
```bash
python -m src.cli verify-secrets
```
This command inspects every tracked file in git using regular expressions for known credential formats:
- Notion Integration tokens (`ntn_...`)
- Firecrawl API keys (`fc-...`)
- Apify API tokens (`apify_api_...`)
- Google AI / Gemini keys (`AIza...`)
- OpenAI keys (`sk-...`)

If any credential is accidentally saved in a tracked file, `verify-secrets` halts execution and pinpoints the file and line number.

---

## 2. Multi-User Database Isolation

### How Local Isolation Works
1. **Local SQLite File:** SQLite is an embedded file database residing directly at `data/jobs.db` on your local filesystem. There is no remote central server.
2. **Custom Database Path:** In `.env`, users can customize `DATABASE_PATH`:
   ```bash
   DATABASE_PATH=data/sushant_jobs.db
   ```
   This allows multiple profiles or candidates to run separate discovery pipelines on the same machine without colliding.
3. **Pristine Initialization:** When a new user clones the repository, no jobs database is included in git. Running `python -m src.cli init` or `python -m src.cli setup` initializes an empty SQLite schema.
4. **Clean Slate Command:** If you ever want to reset your local database to zero, run:
   ```bash
   python -m src.cli reset-db
   ```

---

## 3. How to Obtain Credentials

### A. Tier 1 & Tier 2: 100% Free (No API Keys Required)
* **Tier 1 (Direct ATS APIs):** Directly queries open JSON APIs for Greenhouse, Lever, and Ashby.
* **Tier 2 (JobSpy Aggregators):** Queries LinkedIn, Indeed, and Glassdoor without browser overhead.
* **No keys or credit cards needed!**

### B. Google Gemini API (Recommended)
* **Purpose:** Evaluates job match relevance against your candidate profile and tailors resume bullet points.
* **Cost:** 100% Free on the Gemini 2.5 Flash free tier (15 RPM / 1M TPM).
* **Setup:**
  1. Go to [Google AI Studio](https://aistudio.google.com/).
  2. Click **Create API Key**.
  3. Add to `.env`: `GEMINI_API_KEY=your_key_here` and `LLM_PROVIDER=gemini`.

### C. Apify API Token (Optional: Tier 3 Naukri)
* **Purpose:** Runs cloud-based residential proxy scrapers to bypass Cloudflare anti-bot security on Naukri.
* **Cost:** Free Tier gives **\$5 free monthly credits** (sufficient for hundreds of job scrapes).
* **Setup:**
  1. Sign up at [Apify Console](https://console.apify.com/).
  2. Go to **Settings** -> **Integrations** -> Copy **API Token**.
  3. Add to `.env`: `APIFY_API_TOKEN=your_token_here`.

### D. Firecrawl API Key (Optional: Tier 4 Enterprise SPAs)
* **Purpose:** Extracts structured jobs from complex client-side Single Page Applications (SPAs) like Netflix, Apple, Google, Uber.
* **Cost:** Free Tier gives **500 free scrape credits**.
* **Setup:**
  1. Sign up at [Firecrawl.dev](https://firecrawl.dev/).
  2. Copy your API Key.
  3. Add to `.env`: `FIRECRAWL_API_KEY=your_key_here`.

### E. Notion Integration (Optional: Tabular Tracking Board)
* **Purpose:** Real-time synchronization of discovered, deduplicated opportunities to an interactive Notion table.
* **Setup:**
  1. Go to [Notion Integrations](https://www.notion.so/my-integrations) and click **New integration**.
  2. Name it (e.g., `Job Assistant`) and copy the **Internal Integration Secret** (`ntn_...`).
  3. In Notion, open or create a parent page where your table should live.
  4. Click the `...` menu (top right) -> **Connections** -> Connect your integration.
  5. Copy the Parent Page URL or 32-character ID.
  6. Add to `.env`:
     ```bash
     NOTION_API_KEY=ntn_your_key_here
     NOTION_PARENT_PAGE_ID=your_parent_page_id
     ```
  7. Run:
     ```bash
     python -m src.cli init-notion-db
     ```
     This automatically provisions the table schema and updates `NOTION_DATABASE_ID`.
