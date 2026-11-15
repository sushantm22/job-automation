# Project Decisions

- The initial implementation is a minimal Python project skeleton following the M1 milestone.
- Default config values are intentionally conservative and safe for local testing.
- The app uses SQLite for persistence and keeps the database under the `data/` directory.
- LLM provider support is scaffolded with a generic interface and a mock implementation to keep tests deterministic.
