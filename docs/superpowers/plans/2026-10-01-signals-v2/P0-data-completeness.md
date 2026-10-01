# P0: Data completeness and self-healing (finishing v1)

- **Goal:** the full 10-year history is loaded, verified against SEC's own counts, and kept complete automatically. Every empty view says why it's empty. v1 merges to `main`.
- **Branch:** `feat/sec-dashboard`, continuing v1. **Ledger:** `docs/superpowers/ledgers/v2-p0.md`.
- **Spec:** v2 spec §8 and §4.1 (honest emptiness); v1 plan `08-integration.md`.

## Review Focus

1. A quarter that looks complete because only one form family was counted. Count each family separately.
2. Completeness computed against a stale index (the current quarter is still growing). Exclude today; label the current quarter "in progress".
3. Gap fill queued in a loop for a permanently missing accession (for example SEC returns 404). Mark it `unavailable` after 3 attempts, and show it.
4. Empty-state copy that claims "loading" when the real cause is a mapping failure (for example an unmapped CUSIP).
5. A performance fix that changes results. Every optimization needs a before/after equivalence test.

---

### Task P0.1: Finish v1 plan 08

**Already in progress** in the main checkout:
- the deadlock fix (`a7125b0`)
- catch-up for missed scheduled jobs (`backend/src/signals/catchup.py`)
- the header freshness indicator (`frontend/src/components/layout/FreshnessIndicator.tsx`)

**Steps:**
1. Commit the catch-up work with its tests.
2. Let `backfill_all` run to completion. It resumes after a restart.
3. Finish plan 08 tasks I4–I7, but not the merge (that's P0.6):
   - I4: run the spot-check script on real filings.
   - I5: live latency.
   - I6: Playwright on real data.
   - I7: security sweep, final review and docs.

**Acceptance:**
- every backfill step `done` on `/api/health`
- health `ok`
- plan 08's success criteria met in `docs/superpowers/plans/2026-09-27-sec-dashboard/RESULTS.md`

### Task P0.2: Completeness report

**Files:**
- `backend/src/signals/completeness.py` (new)
- `backend/src/signals/api/routers/health.py` (add an endpoint)
- `backend/src/signals/api/schemas.py` (add schemas)
- tests: `backend/tests/integration/test_completeness.py`

**Interfaces:**
- `index_counts(session, sec, archive, year: int, quarter: int) -> dict[str, int]`
  - Counts accessions per form family (`ownership` = 3/4/5 and their amendments, `form144`, `stakes` = 13D/13G and amendments, `13f` = 13F-HR/NT and amendments) from SEC's `full-index/<year>/QTR<q>/form.idx`.
  - Fetches through `SecClient` and raw-archives the index.
- `stored_counts(session, year, quarter) -> dict[str, int]`: the same families, from `filings` by `filed_date`.
- `completeness_report(session, *, as_of: date) -> CompletenessReport`, which contains:
  - one row per quarter since 2016Q1: indexed, stored, pct, status `complete`/`gap`/`in_progress`
  - insider transactions per year
  - price coverage: the % of price-universe symbols with bars through the last trading day
  - decisions with filed-basis returns and executed-basis returns: the % of those whose 6-month horizon has elapsed
  - fund coverage: tracked funds × quarters present
- Job `completeness_check`:
  - weekly, Sunday 06:00 ET, and also as the last step of `backfill_all`
  - queues `gap_fill` for each family/quarter below 99.5%
  - after 3 failed attempts, marks an accession `unavailable` in `app_state` and stops retrying it
- `GET /api/health/completeness` returns `CompletenessOut`.

**Tests (write first):**
- `test_index_counts_by_family`: on the recorded `full_index` fixture, the counts match the hand-counted values in `manifest`.
- `test_quarter_below_threshold_is_gap`: with seeded filings at 99.0% of the indexed count, the status is `gap`.
- `test_current_quarter_in_progress`: the quarter containing `as_of` gets status `in_progress` and is never `gap`.
- `test_gap_queues_gap_fill_once`: two runs produce one `job_requests` row.
- `test_unavailable_after_three_attempts`: the accession is listed under `unavailable`, and no fourth request is made.
- `test_returns_coverage_counts_both_bases`

**Commit:** `feat: completeness report against SEC full-index counts`

### Task P0.3: "Why empty" states

**Files:**
- `frontend/src/hooks/useCoverage.ts` (new)
- `frontend/src/components/state/EmptyState.tsx` (add a `reason` prop)
- the pages that show performance, ratings or screener results
- MSW handlers and tests

**Behavior:** `EmptyState` gets `reason: "loading" | "insufficient" | "not_covered" | "error"` and shows a matching explanation:
- **loading:** "Performance appears when prices finish loading (37% done)."
- **insufficient:** keep v1's exact "Not enough data yet". Add a second line: "Needs 3+ completed trades (has 1)."
- **not_covered:** "No price data for this security." (for example delisted, or a CUSIP not mapped to a ticker)

**Tests (write first):**
- `renders loading reason with percent`
- `keeps exact insufficient copy`
- `screener empty state explains prices still loading`

**Commit:** `feat(web): explain why views are empty`

### Task P0.4: Measure performance on real data; fix only what misses budget

**Steps:**
1. After the backfill, time each `backfill_all` step and one full `analytics_full` run, and record peak memory (`docker stats`).
2. Record the numbers in plan 08's RESULTS.md.

**Budgets:**
- `analytics_full` ≤ 30 minutes and ≤ 4 GB RSS
- page endpoints p95 ≤ 300 ms (100 sampled requests each)

**If over budget:** fix the measured hot spot. Candidates (from D's report):
- `COPY` into `fund_nav_daily`
- streaming `compute_badges`
- set-based `refresh_feed_items`

Each fix needs an equivalence test: the output tables are identical before and after on the seeded world.

**Commit (only if fixes were made):** `perf(analytics): <what>`

### Task P0.5: Real-data acceptance

**Add** `frontend/e2e/real-data.spec.ts`, run only when `E2E_BASE_URL` is set. It asserts:
- `/company/LEN` lists insider trades in every year from 2016 through 2026, and its 12-month net is not $0 if open-market trades exist in that window
- the screener with default filters shows ≥ 100 insiders
- an insider with ≥ 3 completed decisions shows a curve and windows on both bases ("From filing" and "From trade")
- the funds screener shows ≥ 20 tracked funds with quarterly numbers

**Also** add `backend/scripts/coverage_summary.py`, which prints the completeness report as a table. Paste its output into RESULTS.md.

**Commit:** `test: real-data acceptance for history, performance and screeners`

### Task P0.6: Merge v1 (USER GATE)

**Steps:**
1. Write `docs/superpowers/reports/v2-p0.md`.
2. Ask the user for Claude's review.
3. Fix the findings.
4. Ask the user before merging `feat/sec-dashboard` into `main` (`--no-ff`) and tagging `v1.0`.
