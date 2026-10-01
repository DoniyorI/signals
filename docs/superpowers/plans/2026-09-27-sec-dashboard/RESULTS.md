# Integration results — in progress

Snapshot: 2026-09-30 evening ET. Branch: `feat/sec-dashboard`. The historical backfill is running; this is not a completion report.

| Success criterion | Evidence | Status |
|---|---|---|
| Docker stack and dashboard | Rebuilt db/migrate/api/worker/web; db healthy, migrate exit 0; API health ok, no SEC pause; real feed/screener/watchlists/health and phone feed pass Chromium | Passed |
| Complete historical backfill | Request 3 `backfill_all` running. Reference submissions ZIP retained (1.5 GB, 992,294 members); 6,169,515 acceptance records; 74,031 issuers with SIC; 2016 Q1/Q2 committed. Deadlock fixed in a7125b0 and request 3 resumed at backfill_insiders at 20:38 ET | In progress |
| Feed p95 ≤120 s | Rebuilt worker began at 20:38 ET, outside the qualifying window; next measurement is due 2026-10-01 during 09:00–20:00 ET after one continuous hour. Startup catch-up includes older filings, so current 24-hour p95 is above threshold. One-time 09:15 follow-up scheduled for 2026-10-01; no qualifying one-hour measurement yet | Pending |
| 20 fresh SEC parses match stored data | Script committed; three real-DB/pure comparison regressions pass, including rounding tolerances, missing rows, deterministic sample coverage | Live run and five user eye checks pending |
| Complete profiles and performance | Fixture ingestion → real prices/analytics/API test covers both bases, joint groups, fund curves and idempotent rerun | Historical coverage/timings pending |
| All tests/types/browser routes | Backend: 708 tests, Ruff, Pyright exit 0. Frontend: 112 tests, build/lint exit 0; mock Chromium 12/12; partial real-stack Chromium 5/5. Single migration head, no OpenAPI drift | Local checks passed; full real-profile smoke pending |

SEC access remains capped by the shared client. Raw archives and parsed data are retained. No purchases or remote publishing occurred. No remote is configured.

Security preflight found zero credential/contact matches in tracked patches, no tracked `.env` or `data/`, both ignored, and all published ports bound to localhost. A literal raw `git log` contact scan also matches Git author metadata; source patches were checked separately with `--format=`. Secret values were never printed.

Known nonfatal frontend diagnostics are the TanStack React Compiler compatibility warning and Vite bundle-size warning. Actual multi-million-row analytics memory and duration, complete price/mapping coverage, META/FB history, Good Friday entries, NVDA split returns, and duplicate/reconcile checks remain to be measured against the finished historical data. No live criterion is inferred from fixtures or mock results.

All build decisions are preserved in the [frontend ledger](../../ledgers/07-frontend.md) and [integration ledger](../../ledgers/08-integration.md). The next sub-project remains #2 Signals & alerts after SEC-core acceptance.
