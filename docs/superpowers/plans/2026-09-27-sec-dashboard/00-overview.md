# SEC Insider Dashboard: Implementation Plan (Overview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 1 of the spec. That is a local dashboard of SEC insider trades (Forms 3/4/5), Form 144 notices, 13D/13G stakes and 13F holdings since 2016, with each insider's and fund's track record measured from both the trade date and the filing date.

**Architecture:**
- Postgres 17 stores everything.
- A Python worker is the only process that talks to SEC, Alpaca and OpenFIGI. It ingests, backfills, loads prices and runs analytics.
- A read-only FastAPI app serves the React dashboard.
- Docker Compose runs all four.

The build order is a foundation that locks in every shared contract, then six workstreams in parallel, then one integration pass.

**Tech Stack:**
- **Backend:** Python 3.13, uv, SQLAlchemy 2.1, Alembic 1.20, psycopg 3.3, FastAPI 0.141, httpx 0.28, APScheduler 3.11 (not 4), lxml 6, pandas 3, numpy 2.5, exchange-calendars 4.13, holidays 0.105, rapidfuzz 3.14, yfinance 1.7, Typer, structlog, pytest 9, ruff, pyright.
- **Frontend:** Node 26, Vite 8, @vitejs/plugin-react 6, React 19.3, TypeScript 6.0 (not 7: typescript-eslint needs <6.1), React Router 7.18 (not 8), TanStack Query 5, TanStack Table 8.21 (not 9), TanStack Virtual 3, Tailwind 4.3, shadcn/ui, lightweight-charts 5.2, Recharts 3, openapi-typescript 7, openapi-fetch 0.17, MSW 2, Vitest 4.1, Testing Library, Playwright 1.63.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`. Every plan file argues from it, so read the spec before your plan file.

## Plan files

| File | Owner | Branch | Depends on |
|---|---|---|---|
| `01-foundation.md` | Main agent, in the main checkout | `feat/sec-dashboard`, tagged `foundation` when done | nothing |
| `02-insider-ingestion.md` | Subagent A | `ws/a-insider` | foundation |
| `03-fund-stake-ingestion.md` | Subagent B | `ws/b-funds` | foundation |
| `04-reference-prices.md` | Subagent C | `ws/c-reference` | foundation |
| `05-analytics.md` | Subagent D | `ws/d-analytics` | foundation |
| `06-api.md` | Subagent E | `ws/e-api` | foundation |
| `07-frontend.md` | Subagent F | `ws/f-frontend` | foundation |
| `08-integration.md` | Main agent | `feat/sec-dashboard` | all of the above |

## Global Constraints

Every task in every file implicitly includes these. Values are copied from the spec.

**Toolchain and history**
- Python `>=3.13`. Run everything through `uv run …` from `backend/`. Frontend commands use `npm` from `frontend/`.
- History starts at `BACKFILL_START=2016-01-01`. Form 144 from `2023-04-13`. SCHEDULE 13D/13G from `2024-12-18`.

**Outside traffic**
- SEC traffic is capped at 8 requests/s in total (`SEC_RATE_LIMIT=8`). Every request sends `User-Agent: <SEC_USER_AGENT>` (a name plus an email). An HTTP 403 pauses all SEC traffic for 10 minutes.
- Only the worker calls SEC, Alpaca or OpenFIGI. The API never makes outbound calls. Tests never touch the network; they use `httpx.MockTransport` and recorded fixtures.

**Data rules**
- Raw data is never deleted. Every fetched body is gzip-archived through `RawArchive` before it's parsed.
- Every job is idempotent. Writes are upserts or delete-then-insert keyed by natural keys.
- **Keys:** CIK (int) for companies and people. Accession `0001234567-24-000123` (with dashes) for filings. CUSIP (9 characters, uppercase) for 13F securities. Tickers are dated lookups only. Symbols are canonical dot style (`BRK.B`).
- **Time:** timestamps are `timestamptz`. Business logic runs in `America/New_York` (`signals.domain.calendars.ET`). Price logic uses the NYSE calendar (`XNYS`). Filing-lateness logic uses SEC business days (US federal holidays).
- **13F values:** reported in thousands of dollars for filings made before `2023-01-03`, and in whole dollars from then on. They're stored in dollars.
- **Decisions** are codes `P` and `S` only. 10b5-1 trades are left out of analytics by default, and the `include_10b5_1` toggle adds them back.
- **Horizons:** 1m/3m/6m/12m = 21/63/126/252 trading days. **Windows:** 1y/3y/5y = 252/756/1260 trading days, plus YTD.
- **API number format:** percentages are fractions (`0.123` means 12.3%). Money is USD floats. Dates are ISO strings.

**Errors and security**
- No silent failures. Errors land in `filings.parse_error`, `ingest_runs.errors`, `job_requests.error` or `app_state`, and appear on `/api/health`.
- Ports bind to `127.0.0.1` only: db 5432, api 8000, web 5173.
- Never commit `.env` or anything under `data/`.

**Tests and commits**
- Tests are written first (superpowers:test-driven-development).
- Database tests hit a real Postgres. There are no database mocks.
- Every commit uses a conventional prefix (`feat:`, `fix:`, `test:`, `chore:`, `docs:`) and ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Copy**
- The footer text is exactly `Data from SEC EDGAR. Not investment advice.`

## Plan refinements to the spec

These changes came out of planning. Each one preserves the spec's intent. Implement them as written here.

1. **New tables:**
   - `filing_acceptance` maps each accession to its SEC acceptance time, loaded from `submissions.zip`.
   - `ticker_evidence` holds per-issuer symbol sightings, which rebuild `tickers`.
   - `app_state` is a small key-value store for health data (last poll, SEC block).
2. **`fund_positions` stores one row per filing and CUSIP,** with `accession_no` and `is_effective`, instead of pre-aggregated rows. A restatement then flips `is_effective` without re-parsing anything. Weights live in `fund_position_changes`.
3. **Derived tables gain columns:**
   - `decisions`: `accessions`, `lag_days`, `lag_cost`, `sell_fraction`, `is_new_position`.
   - `decision_returns`: `entry_kind` and `flags`.
   - `profile_stats` and `profile_windows`: `include_10b5_1` joins their keys.
4. **10b5-1 in bulk data.** The Insider Transactions Data Sets have no 10b5-1 checkbox column (confirmed in SEC's readme), so bulk rows use footnote or remarks text. If a future file adds such a column, the loader uses it.
5. **Rebuilding derived tables.** Each table group is replaced in a single transaction. Postgres MVCC means readers see either the old or the new data, never half, which is the same guarantee as the spec's staging-and-swap.
6. **Alpaca feed check.** The first foundation task checks whether the free key can read historical `feed=sip` bars. If SIP is denied, set `PRICE_PRIMARY=yfinance`. Alpaca's IEX-only bars miss trades in thin names, so they're never used for returns.

## Review Focus

These are the five input classes the spec implies that ordinary task tests would miss, most likely first. Each has its test pinned in the owning task.

1. **An issuer changed its ticker** (FB → META), or a ticker was reused by another company. Prices must stitch across the change and returns stay continuous. `/api/companies/FB` resolves to the right issuer. Tests: `05-analytics.md` Task D1 `test_series_stitches_ticker_change`, and `06-api.md` Task E4 `test_company_lookup_by_old_and_reused_ticker`.
2. **A filing accepted on Good Friday** (SEC open, NYSE closed), after an early close, or with an unknown acceptance time. The filed-basis entry must be the next trading session's open. Tests: `05-analytics.md` Task D3 `test_filed_entry_*`.
3. **A brand-new insider with no completed 6-month decisions.** The rating is `null`, the API returns nulls rather than a 500, and the UI shows "Not enough data yet". Tests: D8 `test_rating_none_without_complete_decisions`, E3 `test_insider_header_without_stats`, F5 `renders not-enough-data state`.
4. **A stock split between the trade and the horizon.** The executed price must be converted with that date's `adj_factor`. Tests: D3 `test_executed_entry_applies_split_factor` and D4 `test_returns_across_split`.
5. **A live-feed burst of more than 100 filings between polls.** The poller pages up to 5 pages and the nightly reconcile catches the rest, with no duplicates. Tests: A7 `test_poll_paginates_until_known_accession` and A8 `test_reconcile_ingests_only_missing`.

## Execution protocol

1. **Foundation.** The main agent executes `01-foundation.md` in the main checkout, on branch `feat/sec-dashboard`, and ends by tagging `foundation`.
2. **Dispatch.** Six subagents start in parallel, each with `isolation: "worktree"` from the `foundation` tag. That's exactly 6, and no additional reviewer subagents. Each is told to:
   - read the spec, this overview and its own plan file;
   - use superpowers:executing-plans and superpowers:test-driven-development;
   - create its branch (names in the table above);
   - edit only the files its plan lists;
   - run `uv run pytest -q` (backend) or `npm test` (frontend) before each commit;
   - report the branch, the commits, and any interface deviation.
3. **Ownership.**
   - Files created by the foundation are read-only for workstreams. The exceptions are the stub modules whose owner the foundation names (for example `ingest/handlers/insider.py` belongs to A).
   - A workstream that finds a contract bug stops and reports it instead of changing the contract.
   - Avoid schema changes. If one is unavoidable, add one Alembic revision named `<ws>_<desc>.py` with `down_revision = "0001_initial"`, and report it. Integration merges the heads.
4. **Test database.** Postgres must be running (`docker compose up -d db`). `tests/conftest.py` creates a uniquely named database per pytest session, so parallel worktrees never collide.
5. **Integration.** The main agent executes `08-integration.md`: merge the branches in order C, A, B, D, E, F, run the real backfill, run the spot checks and end-to-end smoke test, and do a final review.
