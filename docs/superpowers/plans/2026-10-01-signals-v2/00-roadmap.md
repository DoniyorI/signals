# Signals v2 roadmap

- **Spec (binding):** `docs/superpowers/specs/2026-10-01-signals-v2-design.md`. The v1 spec still governs everything it covers.
- **Roles:** Claude is architect and reviewer. Executors (GPT or any other coding agent) implement the phase plans below, one task at a time.

## Phases

| Phase | Plan | Goal | Depends on | Size |
|---|---|---|---|---|
| P0 | `P0-data-completeness.md` | Finish v1: full 10-year data, verified and self-healing; merge to `main` | v1 plan 08 (in progress) | S |
| P1 | `P1-redesign.md` | Insight-first, modern UI: Today, Signals, Stock, Person, Fund, Leaderboards | P0 | L |
| P2 | `P2-edge-backtest.md` | Point-in-time edge, signal score v1, Backtest Lab | P1 tasks 1–3 (signals table, design system) | L |
| P3 | `P3-congress.md` | House and Senate trades, members, committee context | P1 tasks 1–3 | L |
| P4 | `P4-options-ideas.md` | Options chains and rule-based ideas for top signals | P2 (score v1) | M |

- **Order:** P0 → P1 → P2 and P3 in parallel → P4.
- **Parallel work:**
  - P2 and P3 may run at the same time only on separate branches, with one executor per branch.
  - Expect small conflicts in `api/schemas.py`, `analytics/run.py`, `frontend/src/App.tsx` and the nav. Whichever branch merges second resolves them.
- **Deferred to after v2:** alert bots, OGE 278e, legislation correlation, public launch and accounts.

## Decisions (defaults; the user can override any time)

- **Visual direction:** B, "modern fintech". The user confirms or changes it at the P1 task 1 gate.
- **Congress data:** official House and Senate sources (free). Quiver (paid) only if the user buys a key.
- **Options data:** Alpaca indicative feed (free). OPRA only with the user's approval.
- **Committee assignments:** current only. Historical later.

## Branches

- **v1 finish:** P0 finishes on `feat/sec-dashboard`. Ask the user before merging it into `main` and tagging `v1.0`.
- **Per phase:** each later phase branches from `main` as `v2/p1-redesign`, `v2/p2-edge-backtest`, `v2/p3-congress` and `v2/p4-options`. It merges back to `main` after its review gate.
- **Never** force-push, rewrite history, or delete branches or worktrees without asking the user.

## Executor protocol (every phase)

1. **Read** `AGENTS.md`, `CLAUDE.md`, the v2 spec, this roadmap, and the phase plan. In `CLAUDE.md`, the hard rules, setup and commands apply.
2. **Setup:**
   - In every checkout or worktree, run `bash scripts/setup-venv.sh` (macOS requires it), then `docker compose up -d db`, then `(cd frontend && npm ci)`.
   - Never replace `backend/.venv` with a real folder.
3. **For each task, in order:**
   1. Write the listed tests first and run them to see them fail.
   2. Implement, then run them to see them pass.
   3. Run all checks with exit codes enforced. In `backend/`: `uv run pytest && uv run ruff format src tests ../scripts && uv run ruff check && uv run pyright`. In `frontend/`: `npm test && npm run build && npm run lint`.
   4. Commit with the task's commit message.
   5. Append to `docs/superpowers/ledgers/v2-<phase>.md` and commit that ledger change too:
      - `Task <id>: complete (commits <base>..<head>, tests: <command> → <result>)`
4. **Rulings.** Where the plan is unclear or conflicts with the spec, decide in the spec's favor, keep going, and record it in the same ledger:
   - `Task <id>: Ruling: <what> — <why> — <cost if wrong>`
5. **Stop and ask the user before:**
   - adding a paid service or a new external account
   - deleting data
   - merging into `main`
   - changing a v1 hard rule
6. **API contract changes:**
   - From `backend/`, run `uv run signals openapi --out ../frontend/src/api/openapi.json`.
   - Then, in `frontend/`, run `npm run gen:api`.
   - Update the MSW mocks in the same task.
7. **Phase end:**
   1. Write `docs/superpowers/reports/v2-<phase>.md`: tasks done, final check output, every ruling, open issues, and screenshots (paths) for UI phases.
   2. Ask the user to have Claude review it.
   3. Fix every Critical and Important finding test-first, then ask the user before merging.

## Review gate (Claude)

When the user says "review <phase>", Claude:
1. Reads the phase report and ledger, and the diff `main..v2/<branch>`.
2. Runs the checks, including Playwright for UI phases.
3. Checks the work against the spec, the plan, and that plan's Review Focus.
4. Appends findings to the report as Critical, Important or Minor, each with its file and line and a failure scenario.

## Executor prompt (paste into GPT; replace `<PHASE>` and `<PLAN FILE>`)

```
You are the executor for phase <PHASE> of the Signals v2 build in /Users/doniyori/Desktop/Signals.
Read, in order: AGENTS.md, CLAUDE.md, docs/superpowers/specs/2026-10-01-signals-v2-design.md,
docs/superpowers/plans/2026-10-01-signals-v2/00-roadmap.md, and docs/superpowers/plans/2026-10-01-signals-v2/<PLAN FILE>.
Follow the roadmap's executor protocol exactly:
- Create or continue the phase branch named in the roadmap.
- Do the tasks in order, test-first, one commit per task.
- Record a ledger line in docs/superpowers/ledgers/v2-<PHASE>.md for every finished task and every ruling.
- Stop at any gate the plan marks USER GATE and ask me.
Check the ledger first. Never redo a task it marks complete.
Never print or commit .env. Never use git stash. Ask me before merging, pushing, deleting data or adding a paid service.
At the end of the phase, write the phase report and tell me it's ready for Claude's review.
```
