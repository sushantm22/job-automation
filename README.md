# Job Application Assistant

A semi-automated job application workflow for finding relevant roles, filtering them by fit, and preparing ATS-friendly application data with a human review gate.

This project is designed to be local-first, deterministic, and safe by default. It does not require a live Gemini integration to be useful; the default LLM path uses a mock client for development and testing.

## Get started in 1 minute

Open this folder in an AI coding assistant that can run commands (Claude Code, Cursor, Codex, GitHub
Copilot agent mode or Gemini CLI) and say **"Set me up"**. It installs everything, asks you a few
questions in the chat, and runs your first job search. Prefer the terminal? See
[QUICKSTART.md](QUICKSTART.md).

## What it does

- discovers roles from company job boards
- filters them by keyword, location, and exclusion patterns
- scores jobs against a stored profile summary
- extracts form fields from ATS pages
- resolves values from a personal profile and answer bank
- presents a review table before any submission decision
- supports Greenhouse, Lever, Ashby, and generic form flows
- keeps job and application state in SQLite

## Current architecture

The project is organized into a few main areas:

- `src/cli.py` — command-line entry points
- `src/config.py` — YAML + environment settings
- `src/db.py` — SQLite schema and persistence
- `src/discovery/` — source-specific job fetching and filtering
- `src/scoring.py` — job matching logic
- `src/answer_bank.py` and `src/answer_resolution.py` — stored answers and form field resolution
- `src/apply/` — ATS-specific and generic application adapters
- `src/orchestrator.py` — central workflow coordination layer
- `src/tailoring.py` and `src/stats.py` — summarization and reporting
- `src/llm/` — LLM abstraction; mock implementation is active by default

## Prerequisites

- Python 3.11+
- Git
- A local environment for Python packages

## Quick start from scratch

1. Open a terminal in the project root.

   Shortcut: `python3 bootstrap.py` (Windows: `py -3 bootstrap.py`) does steps 2–4 in one go
   (virtual environment, requirements, `.env`). Then activate the environment as in step 3.

2. Create a virtual environment:

   ```bash
   python -m venv .venv
   ```

3. Activate it:

   Windows PowerShell:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   Windows cmd:
   ```cmd
   .\.venv\Scripts\activate.bat
   ```

   Bash/zsh:
   ```bash
   source .venv/bin/activate
   ```

4. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Copy the sample environment file:

   ```bash
   copy .env.example .env
   ```

   On Linux/macOS:
   ```bash
   cp .env.example .env
   ```

6. Edit the local config:
   - `config.yaml` controls search terms, locations, and default behavior
   - `.env` is for local environment variables
   - `data/profile.json` stores your candidate profile data

7. Initialize the database:

   ```bash
   python -m src.cli init
   ```

## Important configuration files

### `config.yaml`

Controls the default job search and execution settings, such as:

- keywords (empty by default: each user sets their own job titles during onboarding, saved to `config.local.yaml`)
- locations
- excluded job terms
- max applications per day
- review mode default
- LLM settings

### `.env`

Keep secrets local. The project intentionally avoids committing sensitive values.

### `data/profile.json`

This is the candidate profile used for form filling and matching. It is gitignored so your personal details never get committed. `python -m src.cli setup` creates it from `data/profile.example.json` and asks for the basics; or copy it yourself:

```bash
cp data/profile.example.json data/profile.json
```

## First-run checklist

Before the app is useful, fill in the values in `data/profile.json` that are actually used during matching and form completion.

### Minimum fields to populate

#### Personal details

- `personal.first_name`
- `personal.last_name`
- `personal.email`
- `personal.phone`
- `personal.location.city`
- `personal.location.country`
- `personal.linkedin`
- `personal.github`
- `personal.portfolio` or `personal.website`

#### Work authorization

- `work_authorization.authorized_countries`
- `work_authorization.requires_sponsorship`
- `work_authorization.notes`

#### Preferences

- `preferences.notice_period_days`
- `preferences.expected_salary.min` and `.max`
- `preferences.willing_to_relocate`
- `preferences.remote_preference`
- `preferences.earliest_start_date`

#### Experience and skills

- `experience` with at least a few past roles and companies
- `skills` relevant to your target roles (for example negotiation, CRM and forecasting for sales; Python and APIs for engineering)
- `education` if the application asks for academic history
- `languages` if relevant to the role or region

#### Files

- `files.resume` should point to your actual resume file
- `files.cover_letter_template` if you use one

### Recommended values

- add at least 2-5 meaningful past jobs
- include core technical skills that match your target roles
- keep location and work authorization honest and current
- fill in salary expectations conservatively but realistically

### Fields the system may flag for human review

Some fields are treated as sensitive and are intentionally not auto-filled without review. These include things like:

- criminal history
- visa or sponsorship status
- salary expectations
- work authorization details
- disability or demographic fields

The app is designed to surface these as `needs_human` rather than guessing.

## Typical workflow

Run these commands in order:

```bash
python -m src.cli init
python -m src.cli discover
python -m src.cli score
python -m src.cli list
```

The app is structured so that:

1. jobs are discovered and filtered
2. they are scored against your profile
3. application data is prepared and reviewed
4. ATS adapters handle form filling and submission safely

## Project data files

- `data/jobs.db` — the SQLite database
- `data/profile.json` — your profile and candidate details (gitignored; copy from `data/profile.example.json`)
- `data/candidate_answers_reference.json` — your answers to common extra questions (gitignored; copy from `data/candidate_answers.example.json`)
- `data/target_company_sites.json` — target company and portal list

## Safety and review model

The project intentionally uses a human review gate before form submission in risky cases. This prevents accidental automatic submissions and encourages a supervised workflow.

The review layer is designed to show the user:

- which fields are being filled
- where the answer came from
- whether any fields still need human input

## Testing

Run the test suite from the project root:

```bash
python -m pytest -q
```

Current status: the project is passing its automated checks in the current state.

## Current scope

The project currently includes:

- job discovery and filtering
- scoring and ranking
- form extraction and answer resolution
- Greenhouse, Lever, Ashby, and generic form support
- human review gating
- local SQLite persistence
- resume tailoring and stats helpers

The live Gemini integration is intentionally not enabled in the current implementation, and the system defaults to a mock LLM client for development and test reliability.

## Notes for future expansion

If you want to extend the project later, the best next steps are:

- add more job source adapters
- introduce a proper orchestrator-driven workflow for multi-step application execution
- wire a real provider behind the LLM abstraction
- improve browser automation resilience and error handling

## Troubleshooting

- If commands fail, confirm the virtual environment is active.
- If you do not see jobs, check `config.yaml` and the company source list.
- If profile values are missing, update `data/profile.json` before running the pipeline.
- Keep all secrets in `.env` and do not commit them.

## License

This project is intended for local personal automation and educational use. Use it responsibly and with proper review of all submitted application data.
