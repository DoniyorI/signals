# Signals: SEC insider dashboard

Spec: `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`. Plan: `docs/superpowers/plans/2026-09-27-sec-dashboard/` (start with `00-overview.md`).

## Architecture

Postgres 17 stores everything. A Python **worker** (`signals worker`) is the only process that calls SEC EDGAR, Alpaca or OpenFIGI. It runs scheduled and requested jobs: live feed polling, nightly reconcile, backfills, prices and analytics. A read-only **FastAPI** app (`signals api`) serves the **React** dashboard (`frontend/`). Docker Compose runs `db`, `migrate`, `api`, `worker` and `web`.

## Ground rules (spec §5.4)

1. Raw data is never deleted. Every fetched body is gzip-archived (`RawArchive`) before it's parsed, so any parser can be fixed and data re-derived with `signals reparse`.
2. Every job is idempotent. Writes are upserts or delete-then-insert keyed by natural keys, so reruns are safe.
3. Companies and people are keyed by SEC CIK, filings by accession number (`0001234567-24-000123`), and 13F securities by CUSIP. Tickers are only a dated lookup (`signals.domain.tickers`).
4. Follower returns are measured from the filing's SEC acceptance time (filed basis), not only from the trade date.
5. No silent failures. Errors go to `filings.parse_error`, `ingest_runs`, `job_requests.error` or `app_state`, and appear on `/api/health`.

## Hard rules

- Never measure follower returns from the trade date alone.
- Never key anything by ticker.
- Never delete raw data.
- Every SEC request goes through `signals.sec.client.SecClient`: its User-Agent comes from `SEC_USER_AGENT`, it's capped at 8 requests/s, and a 403 pauses all SEC traffic for 10 minutes.
- Never commit `.env` or anything under `data/`, and never print secrets.
- Two calendars: NYSE trading days (`is_trading_day`) for prices, and SEC business days (`is_sec_business_day`) for filing deadlines. They differ on Good Friday, Columbus Day and Veterans Day.

## Ownership (parallel workstreams)

| Area | Owner |
|---|---|
| Foundation modules (config, db, domain, sec, ingest/pipeline+dispatch, jobs, worker, cli, api/schemas+main+deps+params, analytics/types, prices/base, tests/conftest+factories+support, frontend skeleton) | Main agent. Read-only for workstreams. |
| `ingest/handlers/insider.py`, `ingest/jobs_insider.py`, insider parsers/normalizers/feed/indexes/gap fill/bulk_345 | A: `02-insider-ingestion.md` |
| `ingest/handlers/funds.py`, `ingest/jobs_funds.py`, 13F/13D-G parsers, bulk_13f, fund_changes, `reference/cusip.py`, `reference/tracked_funds.py` | B: `03-fund-stake-ingestion.md` |
| `reference/{sectors,companies,shares,jobs}.py`, `prices/{alpaca,yfinance_provider,universe,loader,jobs}.py` | C: `04-reference-prices.md` |
| `analytics/*` (fills the `curves.py` and `jobs.py` stubs) | D: `05-analytics.md` |
| `api/routers/*`, `api/{pagination,csv}.py`, `api/queries/*` | E: `06-api.md` |
| `frontend/src/**` except `src/api/{openapi.json,schema.d.ts,client.ts}` | F: `07-frontend.md` |

A contract bug means stop and report, not a change to the foundation file. Avoid schema changes. If one is unavoidable, add one Alembic revision `<ws>_<desc>.py` with `down_revision = "0001_initial"`.

## Setup (every checkout and every git worktree)

```bash
bash scripts/setup-venv.sh        # REQUIRED on macOS: see note below
docker compose up -d db           # tests need Postgres; each pytest session creates its own DB
(cd frontend && npm ci)
```

**macOS note:** iCloud "Desktop & Documents" sync marks everything inside dot-folders as hidden, and Python 3.13 skips hidden `.pth` files, which silently breaks the editable install of `signals`. `scripts/setup-venv.sh` makes `backend/.venv` a symlink to `~/.cache/signals-venvs/<path-hash>`. Never replace it with a real `.venv` folder.

## Commands

Backend (from `backend/`):
```bash
uv run pytest                     # all backend tests (real Postgres, no network)
uv run ruff format src tests ../scripts && uv run ruff check
uv run pyright
uv run signals openapi --out ../frontend/src/api/openapi.json   # after any API contract change
uv run signals jobs request backfill_all                        # queue the full backfill
```

Frontend (from `frontend/`):
```bash
npm test && npm run build && npm run lint
npm run gen:api                   # regenerate src/api/schema.d.ts from openapi.json
npx playwright test               # smoke test (mock mode by default)
```

Run checks with their exit codes enforced (don't pipe them through `tail` before committing).

## Testing conventions

- Write tests first (red, then green).
- Database tests use the `session` fixture (one transaction per test, rolled back afterwards). Never mock the database.
- HTTP is mocked with `tests.support.MockRouter` (`httpx.MockTransport`). Unit tests never touch the network.
- Real SEC, Alpaca and OpenFIGI samples live in `backend/tests/fixtures/sec/` and are described in `MANIFEST.json`. Each entry's `expect` holds anchors read independently from the source document, and some entries carry a `structure_note` describing format quirks (13D vs 13G XML, the wrapped daily-index header, and so on). Use `fixture_bytes(key)` and `manifest[key]`.
- Row builders live in `tests/factories.py`.

## Integrated maintenance

All six workstreams are merged into `feat/sec-dashboard`. The ownership table above records the original build boundaries; the main maintainer now owns cross-module integration changes. Keep parser, analytics and API responsibilities in their existing modules, and preserve the generated API contract unless a deliberate contract change is required.

The worker holds a lifetime PostgreSQL advisory lock before startup recovery or SEC-client use. Running requests resume after a restart; failed resumable backfills reuse checkpoints only when kind and parameters match. Scheduled jobs have durable run records; requested partial error results fail visibly. Reference, bulk and gap-fill checkpoints must never mark a failed unit complete.

Price loading bounds provider windows and database batches, probes the latest stored bar for adjusted-history revisions, and refreshes revised history atomically. Use `signals jobs request backfill_prices --params '{"refresh_history":true}'` for older corrections that leave the latest sentinel unchanged or previously unavailable historical bars. Missing prices remain missing.

Live `first_seen_at` measures successful feed availability after its transaction commits. Initial catch-up filings can make latency high; never claim the two-minute target from mock data or exclude those observations without an explicit spec decision.

Integration continuation and rulings: `HANDOFF.md`, `docs/superpowers/ledgers/08-integration.md`, and the current `RESULTS.md`. Real data validation uses `E2E_BASE_URL`, `E2E_INSIDER`, `E2E_COMPANY`, `E2E_FUND` for Playwright. The manual SEC spot-check uses the same worker lock; stop the worker, run the script with a read-only scripts mount, then restart. Never run two independent SEC clients concurrently.
