You are taking over a software project that another coding agent (Claude Code) has partly built. Continue exactly where it stopped. Do not start over.

PROJECT
"Signals" is a local dashboard built from SEC EDGAR data since 2016. It covers:
- insider trades (Forms 3/4/5 and Form 144)
- 5%+ stakes (Schedules 13D/13G)
- fund holdings (Form 13F)

It keeps each insider's and fund's track record, measured from the SEC filing time as well as the trade date.

Stack:
- backend/: Python 3.13, FastAPI, Postgres 17
- frontend/: React 19, TypeScript, Vite
- Docker Compose services: db, migrate, api, worker, web

LOCATION
- Repo: /Users/doniyori/Desktop/Signals. It is a local git repo with no remote. The main working branch, feat/sec-dashboard, is checked out in that folder.
- The unfinished frontend branch, ws/f-frontend, is checked out in its own git worktree: /Users/doniyori/Desktop/Signals/.claude/worktrees/agent-a4052ed686f556203 (.claude is a hidden folder).
- The five backend branches are finished: ws/c-reference, ws/a-insider, ws/b-funds, ws/d-analytics and ws/e-api. Their worktrees are listed in HANDOFF.md.
- /Users/doniyori/Desktop/Signals/.env already exists and is filled in. Don't recreate it, print it or commit it.

READ FIRST (in this order)
1. /Users/doniyori/Desktop/Signals/AGENTS.md
2. /Users/doniyori/Desktop/Signals/CLAUDE.md: architecture, hard rules, ownership, setup and commands. It applies to you too.
3. /Users/doniyori/Desktop/Signals/HANDOFF.md: status, the branch and worktree map, what's left, and the integration follow-ups.
4. docs/superpowers/specs/2026-09-27-sec-dashboard-design.md: the spec, which is the binding authority.
5. docs/superpowers/plans/2026-09-27-sec-dashboard/00-overview.md, then 07-frontend.md and 08-integration.md.
6. The decisions already made, in docs/superpowers/ledgers/*.md.
   - The live frontend ledger is .claude/worktrees/agent-a4052ed686f556203/.superpowers/sdd/07-frontend/progress.md.
   - Its handoff notes matter for the remaining pages: the shared components, the ColumnDef cast pattern in Ruling F4.1, and the test-harness gotchas.

STATUS
- Backend workstreams are done and verified:
  - A: insider ingestion
  - B: 13F and 13D/13G
  - C: reference data and prices
  - D: analytics
  - E: API
- Frontend F:
  - Done: F1–F4 (design tokens and formatters, MSW mock data, shared components and charts, live feed page).
  - Remaining: F5–F13 (insider page, company page, fund page, screener, compare, watchlists, data health, the ⌘K search palette, and a Playwright smoke test).
  - F5 may be partly started. Check `git status` and `git log` in the F worktree first.

STEP 0: MAKE SURE NOTHING ELSE IS RUNNING
Run `git -C /Users/doniyori/Desktop/Signals/.claude/worktrees/agent-a4052ed686f556203 status` twice, a minute apart. If files are changing, stop and ask me: another agent may still be working there.

STEP 1: FINISH THE FRONTEND (plan 07-frontend.md, tasks F5–F13)
- Work in the F worktree's frontend/ folder. node_modules is installed; run `npm ci` only if it's missing.
- You own frontend/src/ only.
  - Never edit src/api/openapi.json, src/api/schema.d.ts or src/api/client.ts; they are the API contract.
  - Change nothing outside frontend/.
- Keep two pieces of copy exact:
  - the footer: "Data from SEC EDGAR. Not investment advice."
  - the empty-rating text: "Not enough data yet"
- All filters live in the URL. "Hide 10b5-1" defaults on (include_10b5_1=false). Basis defaults to filed.
- Before each commit, `npm test && npm run build && npm run lint` must all exit 0.
- For F13, run `npx playwright install chromium`, then `npx playwright test`. It uses mock mode on port 5174; port 5173 belongs to the Docker web container.

STEP 2: INTEGRATE (plan 08-integration.md)
1. In /Users/doniyori/Desktop/Signals (branch feat/sec-dashboard), merge with `git merge --no-ff` in this order: ws/c-reference, ws/a-insider, ws/b-funds, ws/d-analytics, ws/e-api, ws/f-frontend. Resolve conflicts against the spec.
2. Run all checks:
   - `bash scripts/setup-venv.sh`
   - in backend/: `uv run pytest`, `uv run ruff check` and `uv run pyright`
   - in frontend/: `npm ci && npm test && npm run build && npm run lint`
3. Fix every item in HANDOFF.md's "Integration follow-ups" section, test-first.
4. Bring up the stack with `docker compose up -d --build`. The dashboard is at http://localhost:5173 and the API docs are at http://localhost:8000/api/docs.
5. Start the backfill with `docker compose exec worker signals jobs request backfill_all`. It runs for hours and resumes after restarts; progress shows on the Health page.
6. Finish the rest of plan 08: spot checks, latency and performance checks, Playwright on real data, and the security sweep.

HOW TO WORK
- Test-first for every change: write the failing test, run it and watch it fail, implement, then run it and watch it pass.
- Make one commit per task, using the commit message from the plan.
- After each task, append this line to that plan's ledger: `Task N: complete (commits <base>..<head>, tests: <command> → <result>)`.
- Wherever the plan is unclear or conflicts with the spec, decide in favor of the spec and append: `Task N: Ruling: <what> — <why> — <cost if wrong>`.
- Run checks with exit codes enforced; don't pipe them through tail before committing.

HARD RULES
- Never print or commit .env (it holds the SEC contact and the Alpaca API keys). Never commit data/.
- Never key anything by ticker; use the SEC CIK, the accession number or the CUSIP.
- Never measure follower returns from the trade date alone.
- Never delete raw data.
- Every SEC request goes through signals.sec.client.SecClient, which is capped at 8 requests per second.
- macOS: backend/.venv must stay a symlink created by `bash scripts/setup-venv.sh`, because iCloud hides .pth files. Never replace it with a real folder. Run that script in every checkout and worktree before using uv.
- Postgres runs in Docker on 127.0.0.1:5432, and each pytest session creates its own test database. Don't delete the Docker volume.
- Don't use `git stash`; it is shared across worktrees.
- Ask me before you push, force-push, rewrite history, or delete branches or worktrees.

REPORT
After each task, report what you did, the test results and any rulings. At the end, list every ruling from all ledgers and anything unfinished.
