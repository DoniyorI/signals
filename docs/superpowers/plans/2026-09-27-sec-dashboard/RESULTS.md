# Integration results — in progress

Snapshot: 2026-10-02 10:37 ET. Branch: `feat/sec-dashboard`. The historical backfill is running; this is not a completion report.

| Success criterion | Evidence | Status |
|---|---|---|
| Docker stack and dashboard | Rebuilt db/migrate/api/worker/web; db healthy, migrate exit 0; API health warns about pending scheduled catch-up, no SEC pause; real feed/screener/watchlists/health and phone feed pass Chromium | Passed |
| Automatic missed-schedule recovery | Startup catch_up ran again at 22:02:44 ET; durable row and /api/health show done, ran=[], eight jobs behind, deferred because historical backfill is active. Prior real browser showed header warning and catch-up summary; 9/90-day outages and DST verified only in test databases | Implementation and startup detection passed; live repairs deferred |
| Complete historical backfill | Request 3 running, error=null, backfill_reference done; all 42 insider ZIP checkpoints retained. Insider 2026Q3 gap checkpoint complete; Form 144 has 13 quarters complete (2023Q2–2026Q2), with 2026Q3 offset 800 updated Oct 2 10:37 ET. Funds, prices and full analytics pending. Raw archives and completed progress untouched | In progress |
| Feed p95 ≤120 s | Oct 1 check failed (p95=183368.34 s at 12:27 ET) with sleep-interrupted activity. Supplemental Oct 2 10:37 ET API p95=515.26 s, p50=69.82 s; unfiltered rolling SQL cohort 1124 samples, 364 over 120 s and 79 negative delays. Worker zero restarts; latest hour only seven polls, zero errors, 11 pages, max start gap 693.97 s. No SEC pause or parse errors | Target not met; continuous-hour and timestamp integrity acceptance pending |
| 20 fresh SEC parses match stored data | Script committed; three real-DB/pure comparison regressions pass, including rounding tolerances, missing rows, deterministic sample coverage | Live run and five user eye checks pending |
| Complete profiles and performance | Fixture ingestion → real prices/analytics/API test covers both bases, joint groups, fund curves and idempotent rerun | Historical coverage/timings pending |
| All tests/types/browser routes | Backend: 745 tests, Ruff, Pyright exit 0 after six index-recovery/date regressions RED→GREEN. Frontend: 119 tests, build/lint exit 0; prior mock Chromium 12/12 and partial real-stack Chromium 5/5, not rerun for the backend-only fix. Single migration head, no OpenAPI drift | Local checks passed; full real-profile smoke pending |

For the next latency measurement, keep the Mac awake and Docker running for an uninterrupted hour during 09:00–20:00 ET. The October 2 repeat heartbeat is supplemental evidence and does not validate the requested October 1 window. No new automation was created. The 24-hour health selection remains unchanged; older discoveries and negative delay observations were not filtered out.

SEC access remains capped by the shared client. Raw archives and parsed data are retained. No purchases or remote publishing occurred. No remote is configured.

Security preflight found zero credential/contact matches in tracked patches, no tracked `.env` or `data/`, both ignored, and all published ports bound to localhost. A literal raw `git log` contact scan also matches Git author metadata; source patches were checked separately with `--format=`. Secret values were never printed.

Known nonfatal frontend diagnostics are the TanStack React Compiler compatibility warning and Vite bundle-size warning. Actual multi-million-row analytics memory and duration, complete price/mapping coverage, META/FB history, Good Friday entries, NVDA split returns, and duplicate/reconcile checks remain to be measured against the finished historical data. No live criterion is inferred from fixtures or mock results.

All build decisions are preserved in the [frontend ledger](../../ledgers/07-frontend.md), [integration ledger](../../ledgers/08-integration.md), and [v2 P0 ledger](../../ledgers/v2-p0.md). The [initial P0 report](../../reports/v2-p0.md) records the recovery fix and future plan concerns. Continue P0's data completeness/acceptance work, then P1's redesign under the v2 roadmap; P0.1 is not complete.
