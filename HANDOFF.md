# Handoff: build status and how to continue

Snapshot: 2026-09-30. Read `CLAUDE.md` first (architecture, hard rules, setup, commands), then this file.

## Where the work is

Everything lives in this local git repo. There is **no remote**, so nothing is backed up off this Mac.

| Branch | Worktree (under `.claude/worktrees/`) | Plan | Status |
|---|---|---|---|
| `feat/sec-dashboard` | main checkout (this folder) | 01 foundation | Done (tag `foundation`); integration target |
| `ws/c-reference` | `agent-a6a393a9b919d29fa` | 04 reference + prices | Done 7/7 |
| `ws/a-insider` | `agent-a9989974a062c1e17` | 02 insider ingestion | Done 11/11 |
| `ws/b-funds` | `agent-a8381fc340cab38a6` | 03 funds + stakes | Done 8/8 |
| `ws/d-analytics` | `agent-aa2bbeb312058b04a` | 05 analytics | Done 12/12 |
| `ws/e-api` | `agent-afc758e1ee8030ef4` | 06 API | Done 9/9 |
| `ws/f-frontend` | `agent-a4052ed686f556203` | 07 frontend | Done 13/13; merged, mock smoke 12/12 |

- Spec (binding authority): `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`.
- Plans: `docs/superpowers/plans/2026-09-27-sec-dashboard/` (start with `00-overview.md`; integration is `08-integration.md`).
- Progress logs: `docs/superpowers/ledgers/` holds copies of each workstream's ledger. The live ledgers are git-ignored at `<worktree>/.superpowers/sdd/<plan>/progress.md`.
  - `Task N: complete (...)` lines record finished tasks.
  - Every `Ruling:` line is a decision taken during the build. Honor them, and list them in the final report.
- Each finished branch was verified independently: tests, `ruff check` and `pyright` (or `npm test`, `npm run build` and `npm run lint`) all exit 0. Every change stays inside the owning workstream's files, apart from the two exceptions listed under follow-ups.

## What's left

1. **Frontend complete F1–F13.** All workstreams merged C, A, B, D, E, F into `feat/sec-dashboard`. Integration readiness fixes committed: worker bootstrap/singleton/recovery, visible failure diagnostics, retryable historical gaps, fund acceptance repair, bounded atomic adjusted-price repair, and every screener column sortable. Recorded SEC filings pass the real parsers → prices → analytics → API test, including both bases and repeatability. Frontend 119 tests and build/lint pass; prior mock browser 12 tests pass; backend 745 tests and static checks pass after the P0 index-recovery fix. Automatic catch-up is implemented and startup-verified. Live data criteria remain unverified.
2. **Integration** (plan 08):
   - **I1:** complete after cross-workstream commit; full backend suite/static checks and OpenAPI drift pass; migration has one head (`0001_initial`).
   - **I2:** complete; Docker stack and partial real-browser routes verified.
   - **I3:** run the real backfill with checkpoints.
   - **I4:** script and tests committed; fresh SEC historical comparison and five user eye checks pending.
   - **I5:** measure live latency.
   - **I6:** environment-driven routes committed; 12 mock and 5 partial real-stack smoke tests pass; full real profiles, coverage and timings pending.
   - **I7:** run the security sweep, do a whole-branch review, update the docs, and finish the branch.
3. **Integration follow-ups** found during the build (below).

## Integration follow-ups

- **Health "last live poll".** E's health endpoint reads `app_state["live_poll_last_success"] = {"at": <iso>}`. Make sure A's feed poller writes that key after each successful poll. It was built on a separate branch and may not.
- **Health "parse errors in 24h".** It uses `filings.parsed_at`. Confirm the foundation ingest pipeline sets `parsed_at` whenever it parses a filing.
- **Fund numbers are quarterly.** A fund's `profile_stats` "6m" columns (`avg_roi_6m`, `median_6m`, `hit_rate`) hold quarterly excess-return stats. The screener and compare pages must label fund metrics as quarterly.
- **Foundation file touched by E.** `backend/tests/integration/test_api_contract.py`: `test_stub_returns_501` was moved to a throwaway route because `/api/feed` is now real. This was approved in E's pre-flight ruling. Review it on merge.
- **Foundation file touched by F.** Root `.gitignore`: `data/` was changed to `/data/` (it had hidden `frontend/src/mocks/data/`). The same commit is on `feat/sec-dashboard` (14b1870) and `ws/f-frontend` (3047c0c), so the merge is clean.
- **Cross-branch wrappers.** B calls A's `gap_fill` and `apply_acceptance_times`, and D calls B's `compute_fund_changes`, through lazy-import wrappers marked `# pyright: ignore[reportMissingImports]`. After merging, confirm the real signatures still match.
- **Additive interface changes.**
  - A added `load_345_zip(..., *, name=...)`.
  - D's `compute_fund_stats` writes `fund_nav_daily` itself.
  - Analytics runs are serialized with a Postgres advisory lock.
  - A's feed-item upsert resets badges, sector and market cap until the next analytics run.
- **Performance, unmeasured on real data.**
  - About 2.75M `fund_nav_daily` rows per full run, inserted with executemany.
  - One long insider transaction (about 1M decisions and 8M `decision_returns` rows).
  - `compute_badges` loads every decision into memory.
  - `refresh_feed_items` issues about 3 queries per issuer.
  - A cold insider curve against the 300 ms target, and the whole nightly run against its 30-minute target.
- **Frontend gaps.** The feed's "N new filings" 30-second poll pill has no automated test. Desktop screener, compare light/dark and phone insider visually inspected; browser route and filter persistence checks pass.
- **By design.** Scheduled reference jobs restart from scratch after a crash. Only requested jobs resume.

## How to work (same process as the build)

- **Setup in every checkout or worktree:** `bash scripts/setup-venv.sh` (required on macOS; see CLAUDE.md), then `docker compose up -d db`, then `(cd frontend && npm ci)`.
- **Per task:**
  - Write the failing test first and watch it fail.
  - Implement until the tests pass.
  - Run all checks with exit codes enforced.
  - Commit with the plan's message.
  - Add a `Task N: complete (commits <base>..<head>, tests: <command> → <result>)` line to the ledger.
- **Rulings:** decide conflicts against the spec. Record each one as `Task N: Ruling: <what> — <why> — <cost if wrong>`.
- **Secrets:** `.env` holds them. It is git-ignored; never commit or print it. `data/` (raw SEC archive) is never committed either.

## Latest continuation (2026-09-30 evening)
I2 passed. The latest worker rebuild started at **22:02 ET** to activate `d6443ca`. Request **3 backfill_all** resumed at `backfill_insiders`, retaining **22 completed insider quarters** and `progress.done_steps=[backfill_reference]`. Reference is complete: previously measured **6,169,515 acceptance records**, **74,031 issuers with SIC**. Never reset its checkpoints or delete archives.

Deadlock recovery remains in `a7125b0`: complete quarterly load transactions retry 40P01/40001 with fresh sessions and backoff/jitter; canonical ticker evidence and owner writes acquire locks in consistent order. `acda20e` releases the idle transaction on the worker's advisory-lock connection while retaining singleton ownership. `.serena/` is locally excluded in `.git/info/exclude`; never stage it or `.claude/`.

Automatic catch-up is complete in `f5d2e89`, `0000a68`, `0ae801c`: startup plus 15-minute checks, durable missed-job discovery, dependency order, 90-day/DST regressions, full-gap reconciliation, incremental price verification, shared execution guards and SEC-pause waits, health state and header freshness. Full backend **739 tests**, Ruff/Pyright; frontend **119 tests**, build/lint; mock Chromium **12/12** pass. Generated API contract and types are updated.

Deployment: `docker compose up -d --build worker api web` exited 0. Startup catch-up ran at **21:08:06 ET**, recorded `status=done`, `ran=[]`, eight behind jobs and `deferred="Historical backfill is active"`. `/api/health` warns accordingly; the real browser shows the header warning and catch-up summary. This is successful startup detection, not evidence that all scheduled work has caught up. Periodic checks will run repairs after the historical job finishes.

P0's initial review and recovery fix is `d6443ca`: missing quarterly/SEC-business-day indexes now fail visibly without advancing checkpoints; current-quarter detection uses Eastern time; fund/stake gap fills exclude today in Eastern time. Six regression cases were observed RED→GREEN. The full backend has **745 passing tests**, Ruff and Pyright exit 0; frontend **119 tests**, build/lint exit 0; OpenAPI no drift and one Alembic head. Worker-only activation (`docker compose build worker`, then `docker compose up -d --no-deps worker`) exited 0; running source hashes match the committed files. Startup catch-up at **22:02:44 ET** again deferred to request 3; health at **22:08 ET** had no SEC pause or parse errors. API and web were not rebuilt for this backend-only change.

The v2 P0 ledger is `docs/superpowers/ledgers/v2-p0.md` (live copy `.superpowers/sdd/P0-data-completeness/progress.md`); its initial report is `docs/superpowers/reports/v2-p0.md`. P0.1 remains in progress, and P0.2–P0.6 have not started. The report records future plan concerns for Claude: per-family historical coverage start dates, point-in-time score training cutoffs, and P3.6's dependency on P2.1. Continue in the v2 roadmap order; do not skip the P0.6 review/merge gate or P1 mockup choice.

I3–I7 live criteria remain pending. Do not restart the active worker for a spot-check during a healthy quarter; after a suitable checkpoint stop it, run `scripts/spot_check.py` through the same advisory lock using a read-only scripts mount, and restart. The script must respect any persisted SEC pause before fetching. The I5 window is now closed: measure after at least one continuous worker hour on **2026-10-01 between 09:00 and 20:00 ET**, preserving startup catch-up observations. A one-time thread follow-up, `signals-live-latency-validation`, is scheduled for 09:15 on 2026-10-01. Detailed rulings and evidence are in ledger 08. Subagents reached account usage limit; parent continues. Never treat fixtures or mock tests as live historical coverage, latency or performance evidence.
