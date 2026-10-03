# Integration results — in progress

Snapshot: 2026-10-03 09:27 ET. Branch: `feat/sec-dashboard`. The historical backfill is running; this is not a completion report.

| Success criterion | Evidence | Status |
|---|---|---|
| Docker stack and dashboard | Rebuilt db/migrate/api/worker/web; db healthy, migrate exit 0; API health warns about pending scheduled catch-up, no SEC pause; real feed/screener/watchlists/health and phone feed pass Chromium | Passed |
| Automatic missed-schedule recovery | Startup catch_up ran again at 22:02:44 ET; durable row and /api/health show done, ran=[], eight jobs behind, deferred because historical backfill is active. Prior real browser showed header warning and catch-up summary; 9/90-day outages and DST verified only in test databases | Implementation and startup detection passed; live repairs deferred |
| Complete historical backfill | Request 3 resumed with error cleared after 5e4f85f fixed nested TSV paths in the valid 2025 Jun–Aug 13F ZIP. Reference and insider steps complete (42 insider datasets retained); fund datasets advanced from 38 to 40 at Oct 3 09:27 ET. Exact deployed loader hash verified. Remaining fund gaps, prices, full analytics and completeness acceptance pending; raw archives/checkpoints preserved | In progress; ZIP blocker recovered |
| Feed p95 ≤120 s | Oct 1 p95=183368.34 s and Oct 2 p95=515.26 s, both lacking verified continuous active hours. Supplemental Saturday Oct 3 09:16 ET API p95=17051.33 s, p50=1067.38 s; no SEC pause or parse errors. Latest actual Friday feed runs: zero errors, 11–16 pages. The rebuilt worker started Oct 3 09:24 ET. Prior negative-delay integrity issue remains open | No business-day acceptance; target and timestamp validation pending |
| 20 fresh SEC parses match stored data | Script committed; three real-DB/pure comparison regressions pass, including rounding tolerances, missing rows, deterministic sample coverage | Live run and five user eye checks pending |
| Complete profiles and performance | Fixture ingestion → real prices/analytics/API test covers both bases, joint groups, fund curves and idempotent rerun | Historical coverage/timings pending |
| All tests/types/browser routes | Backend: 745 tests, Ruff, Pyright exit 0 after six index-recovery/date regressions RED→GREEN. Frontend: 119 tests, build/lint exit 0; prior mock Chromium 12/12 and partial real-stack Chromium 5/5, not rerun for the backend-only fix. Single migration head, no OpenAPI drift | Local checks passed; full real-profile smoke pending |

For the next latency measurement, keep the Mac awake and Docker running for an uninterrupted hour during 09:00–20:00 ET. The October 2 repeat heartbeat is supplemental evidence and does not validate the requested October 1 window. The existing one-time automation was paused after unintended repeat wake-ups; no new automation was created. October 3 is a Saturday and cannot satisfy business-day acceptance. Two July 22 reconciliation filing errors also remain visible without checkpoint advancement. The 24-hour health selection remains unchanged; older discoveries and negative delay observations were not filtered out.

SEC access remains capped by the shared client. Raw archives and parsed data are retained. No purchases or remote publishing occurred. No remote is configured.

Security preflight found zero credential/contact matches in tracked patches, no tracked `.env` or `data/`, both ignored, and all published ports bound to localhost. A literal raw `git log` contact scan also matches Git author metadata; source patches were checked separately with `--format=`. Secret values were never printed.

Known nonfatal frontend diagnostics are the TanStack React Compiler compatibility warning and Vite bundle-size warning. Actual multi-million-row analytics memory and duration, complete price/mapping coverage, META/FB history, Good Friday entries, NVDA split returns, and duplicate/reconcile checks remain to be measured against the finished historical data. No live criterion is inferred from fixtures or mock results.

All build decisions are preserved in the [frontend ledger](../../ledgers/07-frontend.md), [integration ledger](../../ledgers/08-integration.md), and [v2 P0 ledger](../../ledgers/v2-p0.md). The [initial P0 report](../../reports/v2-p0.md) records the recovery fix and future plan concerns. Continue P0's data completeness/acceptance work, then P1's redesign under the v2 roadmap; P0.1 is not complete.


## October 3 scoped chart recovery and partial coverage

Implementation: `abc5383` loads insider performance independently of the full import; `5e4f85f` handles the valid SEC 13F wrapper-folder ZIP that stopped request 3 after 38 fund datasets. API/web/worker were rebuilt and locally activated. The worker resumed request 3 at 09:24:27 ET with completed reference and insider steps and all fund checkpoints preserved. Remaining global work and all failed historical/latency observations above stay pending.

At 09:30:41 ET, request 3 was running without error and had advanced to **42 completed fund datasets**. The running bulk-loader hash matches the committed source, verifying recovery past the wrapper archive. Later fund/stake/mapping and full price/analytics acceptance remain pending.

Final local checks: backend **816 tests**, Ruff and Pyright passed; frontend **177 tests**, build/lint passed; mock Chromium **12 passed**, four real tests skipped in mock mode. The focused real mature-insider browser test **passed** curves and window results on both bases. The other three live acceptance criteria have not been rerun after the full backfill. Migration head **0002_completeness_members** is applied locally.

Real Buffett request **431**: requested 09:10:50 ET, finished 09:12:10 ET, 41 symbols checked, 39 with provider data, 84,553 stored price rows, 56 decisions, 448 return rows and 12 profile-stat rows; analytics 7.34 s. Filed/executed curves: 2,700/2,703 points through October 2, 53 completed decisions. Missing LBTY and LLYVA.K stay missing. Scoped work does not write global completion state. Screenshot: `docs/superpowers/reports/screenshots/v2-p0-buffett-performance.png`.

For this populated filed chart only, 100 sequential warm requests including JSON decoding: median **69.26 ms**, p95 **244.81 ms**, maximum **1032.42 ms**. Single cold filed/executed requests: **604.96/509.15 ms**. Full nightly duration/RSS and representative endpoint budgets remain unverified.

The following read-only report was captured after request 431 and before request 3 was requeued. Unknown SEC baselines, unsupported eras and partial global coverage are explicit; this is not passing full-history acceptance. The displayed load status reflects that captured moment. No SEC/provider traffic or database writes were made by the report script.

```text
Coverage as of 2026-10-03
SEC baseline: Not checked yet

Quarter  Family      Indexed  Stored    Coverage  Status
2016Q1   ownership       n/a   68,776         n/a  unknown
2016Q1   form144         n/a        0         n/a  not_supported
2016Q1   stakes          n/a        0         n/a  not_supported
2016Q1   13f             n/a    6,072         n/a  unknown
2016Q2   ownership       n/a   53,490         n/a  unknown
2016Q2   form144         n/a        0         n/a  not_supported
2016Q2   stakes          n/a        0         n/a  not_supported
2016Q2   13f             n/a    6,034         n/a  unknown
2016Q3   ownership       n/a   40,073         n/a  unknown
2016Q3   form144         n/a        0         n/a  not_supported
2016Q3   stakes          n/a        0         n/a  not_supported
2016Q3   13f             n/a    6,007         n/a  unknown
2016Q4   ownership       n/a   41,983         n/a  unknown
2016Q4   form144         n/a        0         n/a  not_supported
2016Q4   stakes          n/a        0         n/a  not_supported
2016Q4   13f             n/a    5,994         n/a  unknown
2017Q1   ownership       n/a   70,217         n/a  unknown
2017Q1   form144         n/a        0         n/a  not_supported
2017Q1   stakes          n/a        0         n/a  not_supported
2017Q1   13f             n/a    6,210         n/a  unknown
2017Q2   ownership       n/a   53,955         n/a  unknown
2017Q2   form144         n/a        0         n/a  not_supported
2017Q2   stakes          n/a        0         n/a  not_supported
2017Q2   13f             n/a    6,218         n/a  unknown
2017Q3   ownership       n/a   37,451         n/a  unknown
2017Q3   form144         n/a        0         n/a  not_supported
2017Q3   stakes          n/a        0         n/a  not_supported
2017Q3   13f             n/a    6,207         n/a  unknown
2017Q4   ownership       n/a   40,873         n/a  unknown
2017Q4   form144         n/a        0         n/a  not_supported
2017Q4   stakes          n/a        0         n/a  not_supported
2017Q4   13f             n/a    6,174         n/a  unknown
2018Q1   ownership       n/a   68,559         n/a  unknown
2018Q1   form144         n/a        0         n/a  not_supported
2018Q1   stakes          n/a        0         n/a  not_supported
2018Q1   13f             n/a    6,570         n/a  unknown
2018Q2   ownership       n/a   53,913         n/a  unknown
2018Q2   form144         n/a        0         n/a  not_supported
2018Q2   stakes          n/a        0         n/a  not_supported
2018Q2   13f             n/a    6,622         n/a  unknown
2018Q3   ownership       n/a   38,571         n/a  unknown
2018Q3   form144         n/a        0         n/a  not_supported
2018Q3   stakes          n/a        0         n/a  not_supported
2018Q3   13f             n/a    6,647         n/a  unknown
2018Q4   ownership       n/a   41,008         n/a  unknown
2018Q4   form144         n/a        0         n/a  not_supported
2018Q4   stakes          n/a        0         n/a  not_supported
2018Q4   13f             n/a    6,659         n/a  unknown
2019Q1   ownership       n/a   67,537         n/a  unknown
2019Q1   form144         n/a        0         n/a  not_supported
2019Q1   stakes          n/a        0         n/a  not_supported
2019Q1   13f             n/a    6,887         n/a  unknown
2019Q2   ownership       n/a   53,007         n/a  unknown
2019Q2   form144         n/a        0         n/a  not_supported
2019Q2   stakes          n/a        0         n/a  not_supported
2019Q2   13f             n/a    7,144         n/a  unknown
2019Q3   ownership       n/a   37,647         n/a  unknown
2019Q3   form144         n/a        0         n/a  not_supported
2019Q3   stakes          n/a        0         n/a  not_supported
2019Q3   13f             n/a    6,932         n/a  unknown
2019Q4   ownership       n/a   38,145         n/a  unknown
2019Q4   form144         n/a        0         n/a  not_supported
2019Q4   stakes          n/a        0         n/a  not_supported
2019Q4   13f             n/a    6,981         n/a  unknown
2020Q1   ownership       n/a   69,408         n/a  unknown
2020Q1   form144         n/a        0         n/a  not_supported
2020Q1   stakes          n/a        0         n/a  not_supported
2020Q1   13f             n/a    7,285         n/a  unknown
2020Q2   ownership       n/a   51,459         n/a  unknown
2020Q2   form144         n/a        0         n/a  not_supported
2020Q2   stakes          n/a        0         n/a  not_supported
2020Q2   13f             n/a    7,296         n/a  unknown
2020Q3   ownership       n/a   39,096         n/a  unknown
2020Q3   form144         n/a        0         n/a  not_supported
2020Q3   stakes          n/a        0         n/a  not_supported
2020Q3   13f             n/a    7,157         n/a  unknown
2020Q4   ownership       n/a   43,607         n/a  unknown
2020Q4   form144         n/a        0         n/a  not_supported
2020Q4   stakes          n/a        0         n/a  not_supported
2020Q4   13f             n/a    7,237         n/a  unknown
2021Q1   ownership       n/a   74,944         n/a  unknown
2021Q1   form144         n/a        0         n/a  not_supported
2021Q1   stakes          n/a        0         n/a  not_supported
2021Q1   13f             n/a    7,883         n/a  unknown
2021Q2   ownership       n/a   58,798         n/a  unknown
2021Q2   form144         n/a        0         n/a  not_supported
2021Q2   stakes          n/a        0         n/a  not_supported
2021Q2   13f             n/a    7,927         n/a  unknown
2021Q3   ownership       n/a   44,057         n/a  unknown
2021Q3   form144         n/a        0         n/a  not_supported
2021Q3   stakes          n/a        0         n/a  not_supported
2021Q3   13f             n/a    8,096         n/a  unknown
2021Q4   ownership       n/a   46,675         n/a  unknown
2021Q4   form144         n/a        0         n/a  not_supported
2021Q4   stakes          n/a        0         n/a  not_supported
2021Q4   13f             n/a    7,985         n/a  unknown
2022Q1   ownership       n/a   71,395         n/a  unknown
2022Q1   form144         n/a        0         n/a  not_supported
2022Q1   stakes          n/a        0         n/a  not_supported
2022Q1   13f             n/a    8,921         n/a  unknown
2022Q2   ownership       n/a   55,261         n/a  unknown
2022Q2   form144         n/a        0         n/a  not_supported
2022Q2   stakes          n/a        0         n/a  not_supported
2022Q2   13f             n/a    8,906         n/a  unknown
2022Q3   ownership       n/a   37,955         n/a  unknown
2022Q3   form144         n/a        0         n/a  not_supported
2022Q3   stakes          n/a        0         n/a  not_supported
2022Q3   13f             n/a    8,948         n/a  unknown
2022Q4   ownership       n/a   38,307         n/a  unknown
2022Q4   form144         n/a        0         n/a  not_supported
2022Q4   stakes          n/a        0         n/a  not_supported
2022Q4   13f             n/a    9,010         n/a  unknown
2023Q1   ownership       n/a   69,457         n/a  unknown
2023Q1   form144         n/a        0         n/a  not_supported
2023Q1   stakes          n/a        0         n/a  not_supported
2023Q1   13f             n/a    9,201         n/a  unknown
2023Q2   ownership       n/a   55,207         n/a  unknown
2023Q2   form144         n/a    7,107         n/a  unknown
2023Q2   stakes          n/a        0         n/a  not_supported
2023Q2   13f             n/a    9,113         n/a  unknown
2023Q3   ownership       n/a   37,036         n/a  unknown
2023Q3   form144         n/a    8,252         n/a  unknown
2023Q3   stakes          n/a        0         n/a  not_supported
2023Q3   13f             n/a    9,108         n/a  unknown
2023Q4   ownership       n/a   38,108         n/a  unknown
2023Q4   form144         n/a    8,147         n/a  unknown
2023Q4   stakes          n/a        0         n/a  not_supported
2023Q4   13f             n/a    9,196         n/a  unknown
2024Q1   ownership       n/a   67,671         n/a  unknown
2024Q1   form144         n/a   10,905         n/a  unknown
2024Q1   stakes          n/a        0         n/a  not_supported
2024Q1   13f             n/a    9,666         n/a  unknown
2024Q2   ownership       n/a   52,802         n/a  unknown
2024Q2   form144         n/a    8,705         n/a  unknown
2024Q2   stakes          n/a        0         n/a  not_supported
2024Q2   13f             n/a    9,876         n/a  unknown
2024Q3   ownership       n/a   36,075         n/a  unknown
2024Q3   form144         n/a    9,091         n/a  unknown
2024Q3   stakes          n/a        0         n/a  not_supported
2024Q3   13f             n/a   10,104         n/a  unknown
2024Q4   ownership       n/a   38,547         n/a  unknown
2024Q4   form144         n/a   10,210         n/a  unknown
2024Q4   stakes          n/a        0         n/a  unknown
2024Q4   13f             n/a    9,883         n/a  unknown
2025Q1   ownership       n/a   63,284         n/a  unknown
2025Q1   form144         n/a    9,104         n/a  unknown
2025Q1   stakes          n/a        0         n/a  unknown
2025Q1   13f             n/a   10,677         n/a  unknown
2025Q2   ownership       n/a   50,861         n/a  unknown
2025Q2   form144         n/a    8,241         n/a  unknown
2025Q2   stakes          n/a        0         n/a  unknown
2025Q2   13f             n/a   10,489         n/a  unknown
2025Q3   ownership       n/a   35,457         n/a  unknown
2025Q3   form144         n/a    8,749         n/a  unknown
2025Q3   stakes          n/a        0         n/a  unknown
2025Q3   13f             n/a        0         n/a  unknown
2025Q4   ownership       n/a   36,421         n/a  unknown
2025Q4   form144         n/a    8,646         n/a  unknown
2025Q4   stakes          n/a        0         n/a  unknown
2025Q4   13f             n/a        0         n/a  unknown
2026Q1   ownership       n/a   69,259         n/a  unknown
2026Q1   form144         n/a    9,973         n/a  unknown
2026Q1   stakes          n/a        0         n/a  unknown
2026Q1   13f             n/a        0         n/a  unknown
2026Q2   ownership       n/a   56,103         n/a  unknown
2026Q2   form144         n/a    9,763         n/a  unknown
2026Q2   stakes          n/a        0         n/a  unknown
2026Q2   13f             n/a        0         n/a  unknown
2026Q3   ownership       n/a   37,993         n/a  unknown
2026Q3   form144         n/a    9,084         n/a  unknown
2026Q3   stakes          n/a    1,149         n/a  unknown
2026Q3   13f             n/a    2,176         n/a  unknown
2026Q4   ownership       n/a    1,657         n/a  in_progress
2026Q4   form144         n/a      316         n/a  in_progress
2026Q4   stakes          n/a      107         n/a  in_progress
2026Q4   13f             n/a       76         n/a  in_progress

Insider transactions by year
2016: 397,326
2017: 405,971
2018: 414,201
2019: 399,819
2020: 421,889
2021: 498,196
2022: 397,266
2023: 388,263
2024: 400,927
2025: 383,215
2026: 317,412

Prices through 2026-10-02: 35/13039 (0.3%); no active price load
Six-month returns (elapsed horizons only)
filed: 53/59381 (0.1%)
executed: 53/59593 (0.1%)
Tracked funds: 0; fund quarters: 0/0 (n/a)
Unavailable accessions: 0
```
