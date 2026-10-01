# P1: Insight-first redesign

- **Goal:** replace the table-first UI with an insight-first, modern dashboard: Today, Signals, Stock, Person, Fund and Leaderboards. Every page answers its question before showing details, and is backed by precomputed signals.
- **Branch:** `v2/p1-redesign` from `main`. **Ledger:** `docs/superpowers/ledgers/v2-p1.md`.
- **Spec:** v2 spec §4 (product design), §4.4 (signals), §9 (constraints).

**Stack (unchanged):**
- React 19, Vite, TypeScript 5.9
- Tailwind 4 and shadcn/ui
- TanStack Query and Table
- lightweight-charts for price charts; small SVG for sparklines; Recharts only where it is already used
- openapi-fetch and MSW

## Review Focus

1. Scores that aren't explained. Every score shown must render its chips, and the chips must match `components`.
2. Returns since filing shown without an as-of date, or computed from a stale price without saying so.
3. Planned (10b5-1) trades leaking into "top signals" by default.
4. Charts that break on a symbol with no prices. Show the P0 reason state instead.
5. Phone width (390 px): cards stack, charts resize, no horizontal page scroll, and touch targets are at least 44 px.
6. API latency. Home and stock summary must not run per-row price queries; use precomputed columns or set-based SQL with indexes.

---

### Task P1.1: Three mockup directions (USER GATE)

**Files:**
- `docs/design/v2-mockups/{A-terminal,B-fintech,C-stream}/{today,stock,person}.html`
- `docs/design/v2-mockups/index.html`

**What to build:**
- Static, self-contained HTML/CSS with no build step and no external requests (fonts included).
- Desktop at 1440 px wide and phone at 390 px for each screen (a side-by-side frame, or one file per width).
- Directions as spec §4.5 describes them.
- **Use only fictional sample data**, such as "Northwind Homes (NWH)" and "J. Rivera, CEO". Mark every page "Illustrative sample data". Never use real people or real trades in mockups.
- Show the chips, score, return-since-filing, sparklines, price chart with markers, sentiment bars, and the "after insiders bought" block exactly as spec §4.3 lists them.

**Gate:** stop and ask the user to open `docs/design/v2-mockups/index.html` and pick A, B or C, with any changes they want. Record the choice as a ruling. Don't start P1.5 or any later task before the pick.

**Commit:** `docs(design): three v2 mockup directions`

### Task P1.2: Design system for the chosen direction

**Files:**
- `frontend/src/styles/tokens.css` (new), with the Tailwind theme wired to it
- `frontend/src/components/kit/{KpiStat,SignalCard,Sparkline,ActorChip,ScoreChip,ExplainChips,ChartPanel,SectionHeader}.tsx`
- a dev-only route `/design` (living style guide) that renders every component in light and dark
- tests: `frontend/src/components/kit/*.test.tsx`

**Rules:**
- Self-hosted fonts from npm packages; no CDN.
- Tabular numerals for every number.
- Buy and sell colors are blue and orange, differing in lightness as well as hue.
- Text contrast is at least 4.5:1.
- Dark and light themes both work.
- Keep P0's `EmptyState` reasons.

**Tests (write first):**
- `ScoreChip shows score and tooltip lists components`
- `ExplainChips renders chips in given order`
- `Sparkline renders nothing but an aria-label when no points`
- `SignalCard links ticker, actor and SEC filing`
- `KpiStat formats currency compactly ($1.2M)`

**Commit:** `feat(web): v2 design tokens and component kit`

### Task P1.3: Signals table and interim score v0 (backend)

**Files:**
- `backend/migrations/versions/v2_p1_signals.py`
- `backend/src/signals/analytics/signals.py` (new)
- `backend/src/signals/analytics/run.py`: call `refresh_signals` in the decisions transaction group, for both full and incremental runs
- tests: `backend/tests/integration/test_signals.py`

**Table `signals`:**
- `decision_id` PK, references `decisions`
- `actor_kind`, `actor_id`
- `issuer_cik`, `direction`, `value_usd`
- `filed_at`, `first_trade_date`
- `planned` (bool)
- `score` (smallint 0–100), `score_version` (text), `components` (jsonb), `chips` (text[])
- `ret_since_filing`, `excess_since_filing`, `returns_as_of`
- `updated_at`
- Indexes:
  - `(direction, planned, score desc, filed_at desc)`
  - `(issuer_cik, filed_at desc)`
  - `(actor_kind, actor_id, filed_at desc)`

**Score v0 (exact; P2 replaces it with v1).** Start from 0, add the points below in order, multiply by 0.5 for sells, then clamp to 0–100.

| Component | Points |
|---|---|
| Role: CEO/CFO | 30 |
| Role: other officer | 22 |
| Role: director | 15 |
| Role: 10% owner | 10 |
| Role: other | 5 |
| Size | clamp(6 × log10(value_usd / 25,000), 0, 25) |
| Cluster | +8 per extra distinct owner group, same issuer and direction within 10 trading days; capped at +20 |
| `first_buy_2y` badge | +8 |
| `dip_buy` badge | +8 |
| `big_stake` badge | +6 |
| `form144_matched` badge (sells only) | +4 |
| `late_filing` badge | −5 |
| v1 rating, as a percentile | + 0.15 × rating (no rating → +0) |

Planned (10b5-1) decisions get a row with score 0, `planned=true` and the chip "10b5-1 plan".

**Chips,** in this order:
1. the role ("CEO", "Director", …)
2. "Cluster of N"
3. "First buy in 2y"
4. "Bought after −X% dip"
5. "Stake +Y%"
6. "Late filing"
7. "Rated top Z%"
8. "10b5-1 plan"

**Returns since filing:**
- Last adjusted close as of the run, against the filed-basis entry price; the excess is the same measure minus SPY's.
- `returns_as_of` is the date of that close.

**Tests (write first):**
- `test_ceo_cluster_buy_scores_above_director_small_buy`
- `test_planned_decision_scores_zero_with_chip`
- `test_components_sum_to_score`: before the clamp; for sells, after the 0.5 multiplier
- `test_chips_match_components`
- `test_returns_since_filing_uses_filed_entry_and_spy`
- `test_refresh_is_idempotent`
- `test_incremental_refresh_touches_only_scoped_issuers`

**Commit:** `feat(analytics): signals table with interim score v0`

### Task P1.4: Page APIs (backend)

**Files:**
- routers and queries: `signals`, `home`, `leaderboards`, plus a company summary and a person summary
- `backend/src/signals/api/schemas.py`
- regenerate the OpenAPI document and the frontend types
- tests: `backend/tests/api/test_v2_pages.py`, extending `tests/api/seed.py`

**Endpoints:**
- **`GET /api/signals`** returns `Page[SignalOut]`.
  - Filters: `actor_kind`, `direction`, `min_score`, `role`, `sector`, `since`, `until`, `include_planned=false`, `cluster_min`.
  - Keyset order: `score desc, filed_at desc, decision_id`.
- **`GET /api/home`** returns `HomeOut`:
  - `as_of` and `freshness`
  - `kpis`: buy and sell $ for today and this week, cluster buys this week, new 13D this week
  - `top_signals` (≤ 9, buys, last 7 days)
  - `cluster_buys`
  - `top_rated_buys_30d`
  - `fund_moves`: new or added positions in the latest 13F period, by value
  - `stakes`: 13D in the last 7 days
  - `market`: SPY, QQQ and 11 sector ETFs, each with last, change % and a 60-point sparkline
  - `congress: []` (filled in P3)
- **`GET /api/companies/{ref}/summary`** returns `CompanySummaryOut`:
  - last price, change %, market cap and sector
  - `sentiment` for 3, 6 and 12 months: net, buy and sell $, and buyer and seller counts. Open-market only; planned trades excluded.
  - `after_buys`: n, average excess at 3, 6 and 12 months, and 6-month hit rate (filed basis)
  - `markers`: date, kind (`insider`/`member`/`fund`/`stake`), direction, value, actor name and `decision_id`
- **`GET /api/insiders/{cik}/summary`** returns `PersonSummaryOut`:
  - KPIs for both bases
  - best and worst calls (decision, issuer, 6-month excess)
  - edge (interim: v1 rating and confidence)
  - rank among insiders
- **`GET /api/leaderboards/{kind}`**, where `kind` is `insiders` or `funds` (P3 adds `members`):
  - Ranked by the interim edge (v1 shrunk mean). P2 switches this to PIT edge.
  - Filters: `basis`, `min_n=3`, `role`, `sector`, `limit=50`.
  - Each row: rank, actor, edge, n, hit rate, average excess at 6 months, last trade date and sector.

**SignalOut fields:**
- `id`
- `actor`: kind, id, name, role
- `issuer`: the existing `IssuerRef`
- `direction`
- `value_usd`, `value_min`, `value_max` (the range is null for insiders)
- `first_trade_date`, `last_trade_date`, `filed_at`
- `entry_price_filed`, `entry_price_trade`
- `ret_since_filing`, `excess_since_filing`, `returns_as_of`
- `score`, `score_version`, `components`, `chips`
- `planned`
- `sec_url`

**Tests (write first):**
- `test_signals_default_excludes_planned`
- `test_signals_keyset_pagination_stable`
- `test_home_sections_present_and_bounded`
- `test_company_summary_sentiment_excludes_planned_and_grants`
- `test_after_buys_uses_filed_basis_6m_excess`
- `test_markers_include_buys_sells_and_13d`
- `test_person_summary_best_worst`
- `test_leaderboard_min_n_respected`
- `test_openapi_regenerated` (no drift)

**Commit:** `feat(api): signals, home, summaries and leaderboards`

### Task P1.5: App shell and navigation

**Files:**
- `frontend/src/components/layout/AppShell.tsx`
- `frontend/src/App.tsx` (routes)

**Navigation:**
- Top nav as spec §4.2, plus the ⌘K search, theme toggle and freshness indicator.
- Secondary menu: All filings, Screener, Compare, Data health.
- The footer text stays exactly as v1 until P3.
- On a phone, the nav collapses to a bottom bar of 5 items.

**Routes:**
- `/` → Today
- `/signals`, `/leaderboards`
- `/stock/:ref`, with `/company/:ref` redirecting to it
- `/insider/:cik`, `/fund/:cik`
- `/filings` (the v1 feed)
- `/screener`, `/compare`, `/watchlist`, `/health`

**Tests:**
- `nav shows primary items and secondary menu`
- `company route redirects to stock`
- `phone bottom bar at 390px`

**Commit:** `feat(web): v2 app shell and navigation`

### Task P1.6: Today page

**Layout:** spec §4.3 Today, built from `/api/home` and the kit components.

**States:**
- skeletons while loading
- each section has its own empty state with a reason
- every return shows its as-of date

**Tests:**
- `renders KPI strip from home`
- `top signals show chips and return since filing with as-of`
- `planned trades not in top signals`
- `sections show reasoned empty state`

**Commit:** `feat(web): Today page`

### Task P1.7: Signals page

**Content:**
- A ranked list from `/api/signals`: cards on a phone, rows on desktop.
- Filters held in the URL. "Hide 10b5-1" is on by default.
- Infinite scroll, and CSV export of the current filter.

**Tests:**
- `filters round-trip through URL`
- `score chip tooltip lists components`
- `load more appends without reordering`

**Commit:** `feat(web): Signals page`

### Task P1.8: Stock page

**Content:** spec §4.3 Stock.
- **Hero.**
- **Sentiment bars:** 3, 6 and 12 months.
- **Price chart:**
  - Built with lightweight-charts, with markers from the summary.
  - Range buttons: 1Y (default), 5Y and Max.
  - Hovering a marker shows the trade card.
- **"After insiders bought here"** block.
- **Tabs:** Insiders, Institutions, Filings timeline. Add placeholder tabs for Congress (P3) and Options (P4) only when those phases land, never empty.

**Tests:**
- `chart renders markers by kind`
- `no prices shows P0 reason, no chart`
- `sentiment shows net and counts per window`
- `after-buys hidden when n < 3 with insufficient reason`

**Commit:** `feat(web): Stock page`

### Task P1.9: Person page

**Content:** spec §4.3 Person.
- Hero and KPI row, from the person summary.
- Copycat curve against SPY with a basis toggle (existing performance endpoint).
- Best and worst calls.
- Trade list with outcome chips.
- Holdings.

**Tests:**
- `basis toggle switches curve and KPIs`
- `outcome chips show 6m excess vs SPY`
- `insufficient history uses exact v1 empty-rating copy plus reason line`

**Commit:** `feat(web): Person page`

### Task P1.10: Fund page

**Content:** spec §4.3 Fund.
- Hero and sector allocation bars.
- Top holdings with quarter-over-quarter change, plus new and exited positions.
- Copycat curve against SPY.
- **Fund numbers are quarterly, and are labeled that way everywhere.** This fixes the v1 "6m" label leak.

**Tests:**
- `fund metrics labelled quarterly`
- `new and exited lists from latest period`
- `untracked fund shows not-covered reason`

**Commit:** `feat(web): Fund page`

### Task P1.11: Leaderboards, screener presets, watchlist signals

**Content:**
- **Leaderboards:** tabs for insiders and funds; filters held in the URL; a confidence chip on each row.
- **Screener presets:**
  - "CEO/CFO buys > $250k"
  - "Cluster buys"
  - "First buy in 2 years after a dip"
  - "Top-rated insiders"
- **Watchlist:** shows the latest signals for watched stocks and people.

**Tests:**
- `leaderboard ranks and filters`
- `preset applies URL filters`
- `watchlist shows latest signals for watched items`

**Commit:** `feat(web): leaderboards, presets and watchlist signals`

### Task P1.12: Polish and acceptance

**Steps:**
1. Run Playwright on mock data and on real data (`E2E_BASE_URL`) at 390, 768, 1280 and 1440 px. Save screenshots of every page to `docs/superpowers/reports/v2-p1/`.
2. Run an accessibility pass: keyboard navigation, focus rings, labels, contrast. If you add `@axe-core/playwright` (dev dependency, exact version), note it in the ledger.
3. Measure performance: home and stock time-to-content ≤ 1.5 s on the local stack, and p95 ≤ 300 ms on the page endpoints (100 sampled requests each).
4. Write `docs/superpowers/reports/v2-p1.md` and ask for Claude's review.

**Commit:** `test(web): v2 visual, accessibility and performance acceptance`
