# Integration results — in progress

Snapshot: 2026-10-01 12:27 ET. Branch: `feat/sec-dashboard`. The historical backfill is running; this is not a completion report.

| Success criterion | Evidence | Status |
|---|---|---|
| Docker stack and dashboard | Rebuilt db/migrate/api/worker/web; db healthy, migrate exit 0; API health warns about pending scheduled catch-up, no SEC pause; real feed/screener/watchlists/health and phone feed pass Chromium | Passed |
| Automatic missed-schedule recovery | Startup catch_up ran again at 22:02:44 ET; durable row and /api/health show done, ran=[], eight jobs behind, deferred because historical backfill is active. Prior real browser showed header warning and catch-up summary; 9/90-day outages and DST verified only in test databases | Implementation and startup detection passed; live repairs deferred |
| Complete historical backfill | Request 3 backfill_all remains running with error=null and backfill_reference done. All 42 insider ZIP datasets (2016 Q1–2026 Q2) retained; 2026Q3 gap offset advanced from 62800 at 10:02 ET to 66400 at 12:09 ET. Funds, prices and full analytics remain pending. Raw archives and completed checkpoints untouched | In progress |
| Feed p95 ≤120 s | One-time check: p95=186449.64 s at 10:02 ET and 183368.34 s at 12:27 ET, including startup discoveries. Worker container started Sep 30 22:02:42 ET with zero restarts, but repeated macOS sleep/wake and long poll gaps prevent proof of a continuous active hour. Latest-hour polls: 16 runs, zero errors, seven pages; no active SEC pause or parse errors. 40 negative delay samples also require timestamp/clock investigation | Target not met; qualifying continuous-hour acceptance pending |
| 20 fresh SEC parses match stored data | Script committed; three real-DB/pure comparison regressions pass, including rounding tolerances, missing rows, deterministic sample coverage | Live run and five user eye checks pending |
| Complete profiles and performance | Fixture ingestion → real prices/analytics/API test covers both bases, joint groups, fund curves and idempotent rerun | Historical coverage/timings pending |
| All tests/types/browser routes | Backend: 745 tests, Ruff, Pyright exit 0 after six index-recovery/date regressions RED→GREEN. Frontend: 119 tests, build/lint exit 0; prior mock Chromium 12/12 and partial real-stack Chromium 5/5, not rerun for the backend-only fix. Single migration head, no OpenAPI drift | Local checks passed; full real-profile smoke pending |

For the next latency measurement, keep the Mac awake and Docker running for an uninterrupted hour during 09:00–20:00 ET. No new automation was created. The complete 24-hour health cohort remains unchanged; older discoveries and negative delay observations were not filtered out.

SEC access remains capped by the shared client. Raw archives and parsed data are retained. No purchases or remote publishing occurred. No remote is configured.

Security preflight found zero credential/contact matches in tracked patches, no tracked `.env` or `data/`, both ignored, and all published ports bound to localhost. A literal raw `git log` contact scan also matches Git author metadata; source patches were checked separately with `--format=`. Secret values were never printed.

Known nonfatal frontend diagnostics are the TanStack React Compiler compatibility warning and Vite bundle-size warning. Actual multi-million-row analytics memory and duration, complete price/mapping coverage, META/FB history, Good Friday entries, NVDA split returns, and duplicate/reconcile checks remain to be measured against the finished historical data. No live criterion is inferred from fixtures or mock results.

All build decisions are preserved in the [frontend ledger](../../ledgers/07-frontend.md), [integration ledger](../../ledgers/08-integration.md), and [v2 P0 ledger](../../ledgers/v2-p0.md). The [initial P0 report](../../reports/v2-p0.md) records the recovery fix and future plan concerns. Continue P0's data completeness/acceptance work, then P1's redesign under the v2 roadmap; P0.1 is not complete.
