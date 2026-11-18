# 🌐 Universal AI Agent Prompt

## Best option: an assistant that can run commands
Open this project folder in an AI coding assistant that can run terminal commands, such as Claude Code,
Cursor, OpenAI Codex, GitHub Copilot (agent mode) or Gemini CLI, and say:

> **Set me up.**

Each of these reads the project's instruction file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`,
`.cursorrules` or `.github/copilot-instructions.md`) and follows
[`docs/ONBOARDING_PLAYBOOK.md`](ONBOARDING_PLAYBOOK.md). It installs everything, asks you questions in
chat, runs your first job search and shows the results. You don't type any commands.

## Fallback: a web chat (ChatGPT, Claude.ai, Gemini) that can't run commands
Web chats can't touch your computer, so you'll run the commands they give you. Paste this prompt,
followed by the full contents of `docs/ONBOARDING_PLAYBOOK.md`:

```markdown
You are the setup assistant for the `Automate-Applications` job discovery project, which is on my computer.
You cannot run commands, so follow the onboarding playbook below with this change: give me ONE command at
a time, tell me in one line what it does, and wait for me to paste the output before continuing.
Ask me the playbook's questions in this chat, one topic at a time.
Never ask me to paste API keys here. Tell me to add them to the `.env` file myself instead.
Never suggest `python -m src.cli setup`; use the `python -m src.cli onboard ...` commands from the playbook.

<paste docs/ONBOARDING_PLAYBOOK.md here>
```
