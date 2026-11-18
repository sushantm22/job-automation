# Onboarding Playbook (for AI assistants)

This file tells an AI coding assistant (Claude Code, Cursor, Codex, GitHub Copilot, Gemini CLI, …)
how to set this project up **for** the user, entirely inside the chat. Every tool's instruction file
(`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.github/copilot-instructions.md`) points here.

Use it whenever the user says anything like "set me up", "start using this repo", "get started",
"onboard me", or asks for jobs before setup is complete.

---

## Rules

1. **You run every command yourself, then show the result in chat.** Never reply with "run this in
   your terminal". The only things the user does outside the chat are things only a human can do in
   a browser: creating an account, copying a key, or sharing a Notion page.
2. **Ask questions in chat, one topic at a time.** Say what each answer is used for, and offer the
   current or default value so the user can just say "keep it".
3. **Never run `python -m src.cli setup`.** It is the interactive terminal wizard and will hang
   waiting for keyboard input. Use the `onboard` commands below; they never prompt.
4. **Never run a command that asks for confirmation without its non-interactive flag.** Example:
   `reset-db` requires the user's "yes" in chat and then `reset-db --yes`.
5. **Use the virtualenv's Python directly.** Don't rely on `source .venv/bin/activate`, because
   activation does not persist between your shell calls.
   - macOS / Linux: `.venv/bin/python`
   - Windows: `.venv\Scripts\python.exe`

   Below, `PY` means whichever applies.

   **Always quote the project path.** Folder names often contain spaces, and an unquoted path fails
   with errors like `cd: too many arguments`. Write `cd "/Users/me/my projects/Automate-Applications"`.
6. **Let `onboard status` decide what's next.** After every step run
   `PY -m src.cli onboard status --json` and continue with `next_step`. If the user comes back later,
   it tells you where they left off.
7. **Keep personal data out of git.** `.env`, `config.local.yaml`, `data/profile.json`,
   `data/candidate_answers_reference.json`, `data/resume.*` and `data/jobs.db` are all gitignored.
   Never write keys or personal details into tracked files such as `config.yaml` or docs.
8. **Be honest about failures.** If a command fails, show the important part of the error, explain it
   in plain words, and fix it or offer the next option.
9. **These commands need internet access:** `bootstrap.py` (it runs `pip install`), `onboard check-keys`, `onboard set-key`,
   `init-notion-db`, `discover` and `sync-notion`. If your tool runs commands in a sandbox without
   network access (Antigravity, Codex and others), run these with network access enabled **from the
   first attempt** (for example Antigravity's `BypassSandbox`) instead of waiting for them to fail.
   Offline failures look like `nodename nor servname provided`, `Name or service not known`, or
   `No internet access`; they never mean the user's keys or settings are wrong.
10. **Don't silently change the project's code.** If you find a bug in `src/` while onboarding, explain
   it and ask before editing. Any change stays uncommitted in the user's copy and can clash with their
   next `git pull`, so tell them which files you changed.
11. **Never end a reply by announcing a command.** If you write "I'm running the job search now", that
   same reply must contain the command. A reply that only announces it leaves the user waiting
   with nothing running. For commands that take minutes (`discover`, `sync-notion`), start them in
   the background if your tool allows it (Copilot: run in terminal as a background command; Claude
   Code: `run_in_background`), then check the output about once a minute and tell the user how far
   it has got. Otherwise run them in the foreground with a timeout of about 15 minutes.
   **While a background command runs, only read its output; never run another command in that
   terminal** (not even `ps`): many tools send Ctrl-C first, which kills the run (exit code 130).
   Both commands print progress lines; a minute without a new line is normal while a large
   download or a slow site finishes. Wait for the exit before starting the next command.
12. **Use as few tool calls as possible.** Many tools ask the user to approve every command, so
   combine consecutive commands into one call with `&&` (for example a step's command followed by
   `onboard status --json`), and don't run exploratory commands (`ls`, `which`, guessing paths).
13. **Never write `.env`, `config.local.yaml` or `data/profile.json` by hand, and never fill in
   placeholder values** ("Your Name", example emails). Only the `onboard` commands write these files,
   and only with values the user gave you.

---

## Step 0: Prepare the environment (no questions needed)

Tell the user you are installing things, which takes 1–3 minutes. Then run **one** command from the
project folder (it needs internet access, see rule 9):

`cd "<project folder>" && python3 bootstrap.py` (Windows: `py -3 bootstrap.py`)

It checks Python, creates `.venv`, installs the requirements (skipped when they are unchanged), runs
`onboard prepare` (creates `.env` from `.env.example` so it exists before you ask for any key, the
database and the company list) and prints `onboard status --json`. It's safe to re-run. Don't split it
into separate venv/pip/prepare commands: that only adds approvals for the user.

- If it says Python is missing or too old, this is the one thing the user must install. Point them to
  https://www.python.org/downloads/ (macOS alternative: `brew install python`), wait for them to
  confirm, then run it again.
- Pip cache warnings are harmless. A network/DNS error means rerun with internet access.

Then greet the user with a short plan, for example:
> "You're set up to search for jobs. I'll ask about the roles you want, optional extras like Notion
> tracking, then run your first search. Takes about 5 minutes."

---

## Step `search`: Target roles and locations

This works for **any role**, technical or not: Sales Manager, Marketing Manager, HR Business Partner,
Finance Manager, Operations, Customer Success, SDET and so on. **No roles are shipped as defaults.**
Until the user gives you theirs, `onboard status` shows `roles: []`, `onboard set-search` refuses to
finish, and `discover` refuses to run.

Status shows the current `roles`, `locations` and `exclude`, plus `source`.

- **`roles` is empty (a new user):** ask *"Which job titles should I search for, and where?"* and give
  examples across functions, such as "Sales Manager, Key Account Manager", "Marketing Manager",
  "HR Business Partner", "Financial Analyst", "SDET". Then suggest related titles from the table
  below and let the user confirm the list. Locations default to India and the main cities plus
  Remote; ask only if they want others.
- **`roles` already saved:** ask *"Currently: <roles> in <locations>. Keep these, or tell me yours?"*

How titles are matched (tell the user in one short paragraph, it avoids surprises):
- Only the job **title** counts, never the description.
- Seniority is ignored, so "Sales Manager" also finds Senior, Area and Regional Sales Manager. If
  they don't want a level, add a distinctive word to `--exclude` (for example `--exclude "intern, trainee"`).
  Exclude words are checked in the title, location **and description**, so avoid common words.
- Common abbreviations are understood (Sr/Mgr/Asst, BDM, KAM, HRBP, VP, GM) and so are Indian title
  formats like "Manager - Sales" and "Head of Sales".
- Whole words only: "Sales" does not match "Salesforce Developer".

| If they search for | Suggest also |
|---|---|
| Sales Manager | Business Development Manager, Key Account Manager, Account Manager, Territory Manager, Channel Sales Manager, Sales Head |
| Marketing Manager | Brand Manager, Growth Manager, Marketing Lead, Digital Marketing Manager |
| HR Manager | HR Business Partner, Talent Acquisition Manager, Recruiter |
| Finance Manager | Financial Analyst, FP&A Manager, Accounts Manager |
| Operations Manager | Program Manager, Supply Chain Manager, Project Manager |
| Customer Success Manager | Account Manager, Relationship Manager, Client Partner |
| Category Manager | Category Lead, Category Head, Category Buyer, Merchandising Manager, Buying Manager, Category Marketing Manager |

For category roles, job sites also return **procurement** "category manager" jobs (sourcing of
indirect spend, data-center procurement). They match the title rules; if the user means retail or
e-commerce category management, mention this so they know what those rows are.

Each role adds one LinkedIn search (paced, up to 10 pages) and one search on the other boards,
so **3 to 8 roles** is a good range. The **first
role** is also the search term on the big-company career sites (Google, Amazon, Microsoft and
others, used only if a Firecrawl key is added), so put the user's main title first.

- Save the roles: `PY -m src.cli onboard set-search --roles "Sales Manager, Key Account Manager, Business Development Manager" --locations "India, Remote, Pune"`
- Keep what is already saved: `PY -m src.cli onboard set-search` (fails on a fresh install: there is nothing to keep)
- Optional `--exclude "intern, unpaid"`: words that reject a job.

Choices are saved to `config.local.yaml` (gitignored). `config.yaml` is never modified.

---

## Step `api_keys`: Optional extra sources

First explain that **no keys are needed to start**. The free sources (company job boards and
LinkedIn/Indeed/Glassdoor/Naukri via JobSpy) already work. Then offer the extras:

| Key | What it adds | Where to get it (free tier) |
|---|---|---|
| `NOTION_API_KEY` | Sends jobs to a Notion table (next step) | https://www.notion.so/my-integrations → New integration → copy the "Internal Integration Secret" (`ntn_…`) |
| `APIFY_API_TOKEN` | Backup source for Naukri when JobSpy gets blocked | https://console.apify.com/account/integrations ($5/month free credit) |
| `FIRECRAWL_API_KEY` | Career sites of ~20 big companies (Google, Apple, Flipkart, …) | https://firecrawl.dev → API Keys (500 free credits) |

Do **not** offer `GEMINI_API_KEY`. Nothing uses it yet.

**How the user gives you a key.** Offer both options, the first time a key comes up:
- **Paste it in this chat.** Mention once that whatever is typed in chat is sent to the AI provider
  this tool uses. Then save it with the value on stdin, so it is never written as a command argument:
  `printf '%s' '<KEY>' | PY -m src.cli onboard set-key NOTION_API_KEY`
  (Windows PowerShell: `'<KEY>' | PY -m src.cli onboard set-key NOTION_API_KEY`)
- **Add it themselves.** `.env` already exists in the project folder (step 0 created it; if it's
  missing, run `onboard prepare` again). They open it, put the key after the matching `=` (for example
  `NOTION_API_KEY=ntn_…`), save, and say "done". Then run `PY -m src.cli onboard check-keys`. It tests
  each key online and prints only `verified`, `failed`, `missing` or `set (no online check)`, never the value.

The command reports `verified online`, `online check FAILED`, `no online check`, or `couldn't check: no
internet access`. Only `FAILED` means the key is wrong; then ask for it again, because it was probably
copied incompletely. `couldn't check` means the command had no network access: rerun it with network
access (rule 9), and don't ask the user for a new key.

Never repeat a key back in chat, never print `.env`, and never log a key.

If the user wants no extras: `PY -m src.cli onboard skip api_keys`

---

## Step `notion`: Optional Notion tracking table

- If `NOTION_API_KEY` is not set and the user doesn't want Notion: `PY -m src.cli onboard skip notion`.
- Otherwise, guide them through the one browser-only part:
  1. In Notion, open or create the page where the job table should live.
  2. Click `•••` (top right) → **Connections** → select the integration they created.
  3. Copy the page link (`•••` → **Copy link**) and paste it here.
- Then run `PY -m src.cli init-notion-db --parent-page-id "<page link>"`
  This creates the table and saves `NOTION_DATABASE_ID` to `.env` automatically. Tell the user the
  table ("Automated Job Applications") now appears directly on the page they shared, and share the
  table URL it prints.
- If it fails, the command prints Notion's own error message. When it also shows the
  "Connections" tip (404, 401 or 403), the page wasn't shared with the integration, so repeat step 2.
  Any other message (for example a 400 `validation_error`) is a problem in the request, not the user's
  setup. Explain it and don't ask them to re-share the page.

---

## Step `first_discovery`: First job search

Run the free sources **in this same reply** (rule 11), as one background command in two parts, so
the user approves once and the first results reach Notion before the slow part starts:

`PY -m src.cli discover --tiers 1 && PY -m src.cli discover --tiers 2`

- Part 1 (tier 1): company job boards and the JobHive dataset (16 company ATS sources such as
  Workday, Oracle, SuccessFactors, Phenom, Amazon, Greenhouse and Zoho Recruit; India rows only).
  A few minutes; about 100 MB is read on the first run of the day, nothing when the data is unchanged.
- Part 2 (tier 2): LinkedIn, Indeed, Naukri and Glassdoor. The **first** search for a set of roles
  looks back `search.max_job_age_days` (30 days) and asks each site for up to 100 jobs per role.
  LinkedIn is paced (a pause between roles, and a one-minute wait if it rate-limits us), so this
  part often takes 5–10 minutes. **Later runs only look back to the previous run** and are much
  faster. Changing the roles starts a full 30-day search again.

(Use plain `discover` to also include Apify and Firecrawl if those keys were added.) Use background
runs or long timeouts as described in rule 11, and report part 1's results as soon as its table
appears in the output. Progress lines show it is moving: `[Tier 1] Checking N company job boards...`,
`[Tier 1] 50/207 boards checked...`, `[JobHive] workday: N India rows of M (... MB). (3/16)`,
`[Tier 2] LinkedIn: '<role>' in India (1/4)...`, `[Tier 2] LinkedIn rate-limited ...; waiting 60s`
and `[Notion Sync] Sending N jobs to Notion...`.

**Freshness rules (explain these to the user after the first run):**
- Job boards: jobs posted more than `search.max_job_age_days` ago (default 30) are skipped.
  Company career sites (JobHive sources, the direct company boards): `search.max_company_job_age_days`
  (default 60), because a job still listed on a company's own site is still open. Stored jobs are
  closed once they pass their limit.
- Workday and most SuccessFactors jobs have **no posting date**. The first run records what is
  currently listed as a baseline **without adding it**. The summary says how many of the user's
  *matching* jobs were held back this way ("held back N matching Workday/SuccessFactors jobs").
  From the next daily update on, only jobs that newly appear are added (at most about a day old).
  Users who prefer the full undated backlog can set `search.undated_jobs: include`.

Afterwards:
- Summarize the results table: jobs fetched, how many matched, how many were new, and how many were
  synced to Notion.
- **If the output says "N more jobs are waiting for Notion"**: each `discover` run pushes at most 200
  new rows (`notion.max_sync_per_run` in `config.yaml`). Tell the user, then run
  `PY -m src.cli sync-notion` (pushes all of them; allow a long timeout or run it in the background,
  since Notion accepts about 3 rows per second).
- **If the output lists "Close titles found"** (titles the job sites returned for the user's
  searches that don't match a role yet, with counts, e.g. "Category Lead (6), Category Buyer (3)"):
  show them and ask which to add. Then save the current roles plus the chosen ones with
  `onboard set-search --roles "..."` (it replaces the list) and run the search again. The new roles
  get a full 30-day search.
- Run `PY -m src.cli list` and show a sample of the matches as a table in chat (company, title,
  location). JobHive jobs have no posting date, and Oracle-hosted employers may show internal codes
  (e.g. "Hcbt") instead of company names.
- **If 0 matched:** the role titles are probably too narrow. Suggest broader or additional titles and
  go back to the `search` step. The filter keeps only jobs whose **title** matches a role (see the
  matching rules in the `search` step), located in India or remote. Seniority is ignored, and the
  description is never used.

---

## Step `profile`: Candidate profile (needed later for applying, not for searching)

Explain that the profile is only needed when applying to jobs, which is not built yet, so it can be
skipped for now (`PY -m src.cli onboard skip profile`).

If they want to fill it in, ask in one message for: first and last name, email, phone with country
code, city, country, LinkedIn URL, GitHub URL (optional), notice period in days, and the path to
their resume file. Mention that these details go through this chat, or they can fill in
`data/profile.json` themselves.

`PY -m src.cli onboard set-profile first_name=Asha last_name=Rao email=asha@example.com "phone=+91 90000 00000" city=Pune country=India linkedin=https://linkedin.com/in/asha notice_period_days=30 "resume=/Users/asha/Downloads/Asha CV.pdf"`

Quote any value containing spaces. A resume outside the project is copied to `data/resume.pdf`
(gitignored). The command lists anything still missing.

Experience, education and skills: the user can edit `data/profile.json` directly, or tell you and you
edit the JSON for them. Common screening answers (CTC, notice period, etc.) go in
`data/candidate_answers_reference.json`.

---

## Finish

When `onboard status` reports `"complete": true`, summarize what is configured and tell the user what
they can simply **ask you** from now on:

| User says | You run |
|---|---|
| "Find new jobs" | `PY -m src.cli discover --tiers 1,2` (or `discover` with keys), then `list` |
| "Show my jobs" | `PY -m src.cli list` |
| "Sync to Notion" | `PY -m src.cli sync-notion` |
| "Remove old jobs" | `PY -m src.cli prune-old` (closes jobs past the age limit; Notion rows → Closed) |
| "Change my roles" | `PY -m src.cli onboard set-search --roles "…"` |
| "Start over / clear my jobs" | Confirm in chat first, then `PY -m src.cli reset-db --yes` |
| "Is anything leaking?" | `PY -m src.cli verify-secrets` |

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `pip install` fails building numpy/pandas | Python is too new for a pinned wheel. Recreate the venv with Python 3.12/3.13 (`python3.12 -m venv .venv`). |
| `ModuleNotFoundError: src` | Run commands from the project root folder. |
| Tier 1 shows `Board '<company>' no longer exists (404)` | That company left its job-board provider. It's removed from the user's registry automatically. |
| Tier 2 returns 0 or errors | Job sites rate-limit scrapers. Try again later; tier 1 still works. |
| Notion `object_not_found` / 404 | The parent page isn't shared with the integration (Notion step 2). |
| "Couldn't reach Notion", `nodename nor servname provided`, `Name or service not known` | A network/DNS problem; the request never reached Notion, so the user's setup is fine. The command already retries briefly. Run it again. If your tool sandboxes commands, run it with network access allowed (or ask the user to approve that). Never send the user back to Notion's settings for this. |
| `CERTIFICATE_VERIFY_FAILED` / "Couldn't verify ... security certificate" | A certificate setup problem on this computer, not the user's keys. The CLI already uses the operating system's certificate store; if it still happens with python.org's Python on macOS, run `/Applications/Python 3.x/Install Certificates.command` once. Don't ask the user for a new key. |
| Firecrawl "read operation timed out" | That career site was slow; it's skipped this run and retried next time. |

## Chat tools that can't run commands (ChatGPT/Claude/Gemini on the web)

They cannot run anything on the user's computer. Recommend an assistant that can (Claude Code,
Cursor, Codex, Copilot agent mode or Gemini CLI). If the user still wants to continue there, give
**one command at a time**, ask them to paste the output back, and follow the same steps.
