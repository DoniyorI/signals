# Instructions for coding agents

This project was built by Claude Code, and any agent can continue it.

1. Read `CLAUDE.md`. Its architecture, ground rules, hard rules, ownership table, setup and commands apply to every agent.
2. Read `HANDOFF.md` for current status, where each branch and worktree is, what's left, and the integration follow-ups.
3. The spec is the binding authority: `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`. The plans are in `docs/superpowers/plans/2026-09-27-sec-dashboard/`.
4. Work test-first, and commit once per task with the plan's commit message.
   - Record each finished task and each decision in that plan's ledger, in the format described in HANDOFF.md.
   - The live ledgers are `<worktree>/.superpowers/sdd/<plan>/progress.md`. Copies are in `docs/superpowers/ledgers/`.
5. Never commit or print `.env` (it holds secrets), and never commit `data/`.
