---
name: onboard
description: Set up Automate-Applications for a new user entirely in chat — install dependencies, ask for target roles, optional API keys and Notion, run the first job search, and show results. Use when the user says "set me up", "get started", "start using this repo", "onboard me", or asks to find jobs before setup is complete.
---

# Onboard the user (in chat)

Follow [`docs/ONBOARDING_PLAYBOOK.md`](../../../docs/ONBOARDING_PLAYBOOK.md) from the top. Read it now
if it isn't already in context.

Core rules, in short:
- Run every command yourself with Bash and show the results in chat. Never tell the user to run commands.
- Ask the playbook's questions in chat, one topic at a time; use AskUserQuestion when the choices are clear-cut.
- Never run `python -m src.cli setup` (interactive; it hangs). Use `.venv/bin/python -m src.cli onboard ...`.
- `pip install`, `check-keys`, `set-key`, `init-notion-db`, `discover` and `sync-notion` need internet access;
  if commands run sandboxed, enable network access on the first attempt.
- Step 0 is one command: `cd "<project folder>" && python3 bootstrap.py` (venv, requirements, `onboard prepare`, status). Don't split it.
- Combine consecutive commands with `&&`; never hand-write `.env`, `config.local.yaml` or `data/profile.json`, and never use placeholder values.
- After each step run `.venv/bin/python -m src.cli onboard status --json` and continue with `next_step`.
- Secrets go to `.env` via stdin (`printf '%s' '<KEY>' | .venv/bin/python -m src.cli onboard set-key NAME`)
  or the user adds them to `.env` themselves, after which you run `onboard check-keys`. Never echo a key or print `.env`.
- Run `discover` in the same reply you announce it, with `run_in_background`, and check its output about once a minute (tier 2 scrapes several job sites and can take 5–10 minutes). Use the playbook's single command `discover --tiers 1 && discover --tiers 2`.
