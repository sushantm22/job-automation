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
- After each step run `.venv/bin/python -m src.cli onboard status --json` and continue with `next_step`.
- Secrets go to `.env` via stdin (`printf '%s' '<KEY>' | .venv/bin/python -m src.cli onboard set-key NAME`)
  or the user adds them to `.env` themselves. Never echo a key or print `.env`.
- Give `discover` a long timeout (around 10 minutes), since tier 2 scrapes several job sites.
