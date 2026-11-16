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
6. **Let `onboard status` decide what's next.** After every step run
   `PY -m src.cli onboard status --json` and continue with `next_step`. If the user comes back later,
   it tells you where they left off.
7. **Keep personal data out of git.** `.env`, `config.local.yaml`, `data/profile.json`,
   `data/candidate_answers_reference.json`, `data/resume.*` and `data/jobs.db` are all gitignored.
   Never write keys or personal details into tracked files such as `config.yaml` or docs.
8. **Be honest about failures.** If a command fails, show the important part of the error, explain it
   in plain words, and fix it or offer the next option.
9. **These commands need internet access:** `pip install`, `onboard check-keys`, `onboard set-key`,
   `init-notion-db`, `discover` and `sync-notion`. If your tool runs commands in a sandbox without
   network access (Antigravity, Codex and others), run these with network access enabled **from the
   first attempt** (for example Antigravity's `BypassSandbox`) instead of waiting for them to fail.
   Offline failures look like `nodename nor servname provided`, `Name or service not known`, or
   `No internet access`; they never mean the user's keys or settings are wrong.
10. **Don't silently change the project's code.** If you find a bug in `src/` while onboarding, explain
   it and ask before editing. Any change stays uncommitted in the user's copy and can clash with their
   next `git pull`, so tell them which files you changed.

---

## Step 0: Prepare the environment (no questions needed)

Tell the user you are installing things, which takes 1–3 minutes. Then:

1. Check Python is 3.10 or newer: `python3 --version` (Windows: `py -3 --version`).
   - If it is missing or older, this is the one thing the user must install. Point them to
     https://www.python.org/downloads/ (macOS alternative: `brew install python`), wait for them to
     confirm, then continue.
2. If `.venv` does not exist: `python3 -m venv .venv` (Windows: `py -3 -m venv .venv`).
3. Install dependencies: `PY -m pip install -r requirements.txt`. **This downloads packages, so it
   needs internet access:** if your tool sandboxes commands, run it with network access enabled on
   the first attempt (rule 9). Pip cache warnings are harmless.
4. Run `PY -m src.cli onboard prepare`. It creates `.env` from `.env.example`, so the file exists
   before you ever ask for a key, and also creates the database and loads the company list. It's safe
   to re-run.
5. Run `PY -m src.cli onboard status --json` and greet the user with a short plan, for example:
   > "You're set up to search for jobs. I'll ask about the roles you want, optional extras like Notion
   > tracking, then run your first search. Takes about 5 minutes."

---

## Step `search`: Target roles and locations

Status shows the current `roles`, `locations` and `exclude`, plus `source`. When `source` is
`config.yaml (shared defaults)`, those are the project's example values (SDET/QA roles in India),
not the user's own choices.

Ask: *"Which job titles should I search for, and where? Currently: <roles> in <locations>. Keep
these, or tell me yours."* Suggest including seniority variants (e.g. "Backend Engineer, Senior
Backend Engineer").

- Keep the current values: `PY -m src.cli onboard set-search`
- New values: `PY -m src.cli onboard set-search --roles "Backend Engineer, Python Developer" --locations "India, Remote, Pune"`
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

Say it takes a few minutes. Then run the free sources:

`PY -m src.cli discover --tiers 1,2`

(Use plain `discover` to include Apify and Firecrawl if those keys were added.) Give the command a
long timeout, around 10 minutes, because JobSpy (tier 2) scrapes several job sites one after another.

Afterwards:
- Summarize the results table: jobs fetched, how many matched, how many were new, and how many were
  synced to Notion.
- Run `PY -m src.cli list` and show the matches as a table in chat (company, title, location).
- **If 0 matched:** the role titles are probably too narrow. Suggest broader or additional titles and
  go back to the `search` step. The filter keeps only jobs whose **title** matches a role (or core QA
  terms), located in India or remote.

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
| Firecrawl "read operation timed out" | That career site was slow; it's skipped this run and retried next time. |

## Chat tools that can't run commands (ChatGPT/Claude/Gemini on the web)

They cannot run anything on the user's computer. Recommend an assistant that can (Claude Code,
Cursor, Codex, Copilot agent mode or Gemini CLI). If the user still wants to continue there, give
**one command at a time**, ask them to paste the output back, and follow the same steps.
