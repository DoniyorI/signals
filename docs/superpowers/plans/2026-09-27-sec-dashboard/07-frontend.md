# Workstream F: Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every dashboard page in spec section 11 (feed, insider, company, fund, screener, compare, watchlists, health, and ⌘K search) against the typed API contract. The pages are developed and tested with MSW mocks, so this workstream never waits on the real API.

**Architecture:**
- Each page is a React Router route component that reads its state from the URL and fetches through TanStack Query with `openapi-fetch`.
- Shared components hold tables, chips and charts. Pure formatting and mapping functions are unit-tested.
- MSW handlers serve typed fixtures that are consistent with the API seed world.

**Tech Stack:** React 19.3, TypeScript 6.0, Vite 8, React Router 7.18, TanStack Query 5, TanStack Table 8.21, TanStack Virtual 3, Tailwind 4.3, shadcn/ui, lightweight-charts 5.2, Recharts 3, openapi-fetch 0.17, MSW 2.15, Vitest 4.1, Testing Library, Playwright 1.63.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, section 11 (pages), 9.8 (badge meanings) and 10 (endpoints).

## Global Constraints

Everything in `00-overview.md` › Global Constraints. On top of that:
- Work on branch `ws/f-frontend`. You own everything under `frontend/src/` except `src/api/openapi.json`, `src/api/schema.d.ts` and `src/api/client.ts` (the foundation's contract).
- Never hand-edit the generated types. If the contract looks wrong, stop and report it.
- **Before Task F1**, invoke the `frontend-design` skill for the visual direction and the `dataviz` skill before any chart work. Follow both.
- The layout is dense and data-first, with light and dark themes. Numbers use tabular figures.
- It must work at 1280px and above, and degrade gracefully down to a 390px phone width without horizontal page scroll. Tables scroll inside their own container.
- **URL state:** all page filters live in the URL (`useSearchParams`), so views are shareable and reload-safe.
- **Default toggles:** the "Hide 10b5-1" toggle is on by default (`include_10b5_1=false`), and the basis toggle defaults to `filed`.
- **Every SEC-derived number** links to its filing. External links use `target="_blank"` with `rel="noreferrer"`.
- **Copy:**
  - The empty-rating text is exactly `Not enough data yet`.
  - The footer (already in AppShell) stays exactly `Data from SEC EDGAR. Not investment advice.`
- Run `npm test` before every commit.

## Review Focus

- Overview item 3 (empty profiles): F5 `renders not-enough-data state`.
- A fund that isn't tracked shows `Performance is available for tracked funds only` instead of an error: F7 `untracked fund message`.

## Interfaces consumed (from the foundation)

- `api` (the openapi-fetch client) and the `Schema<...>` type helper from `src/api/client.ts`. The generated `paths` and `components` types.
- `AppShell`, the route table in `App.tsx` (pages are imported by the file names already created), the MSW setup (`src/mocks/browser.ts`, `src/mocks/node.ts`, `src/test/setup.ts`) and the installed shadcn components.

## Interfaces produced

- `src/lib/format.ts`: `fmtUsd`, `fmtUsdFull`, `fmtPct`, `fmtShares`, `fmtDate`, `fmtDateET`, `fmtRelative`, `ratingLabel`
- `src/lib/badges.ts`: `BADGE_LABELS`, `BADGE_HELP` and `PLAN_LABELS`
- Components under `src/components/`:
  - `data/DataTable.tsx`, `data/BadgeChip.tsx`, `data/PlanChip.tsx`, `data/RatingPill.tsx`, `data/ReturnCell.tsx`, `data/SecLink.tsx`, `data/WindowsTable.tsx`, `data/ChangeChip.tsx`
  - `controls/BasisToggle.tsx`, `controls/TenB51Toggle.tsx`, `controls/QuarterSelect.tsx`
  - `state/EmptyState.tsx`, `state/ErrorState.tsx`
  - `charts/PriceChart.tsx`, `charts/EquityChart.tsx`, `charts/ValueChart.tsx`, `charts/AllocationDonut.tsx`, `charts/mapping.ts`
  - `search/SearchPalette.tsx`
- Hooks: `src/hooks/useUrlState.ts` and `src/hooks/useWatch.ts`
- Mocks: `src/mocks/data/*.ts` and `src/mocks/handlers.ts`

---

### Task F1: Design tokens and formatters

**Files:**
- Modify: `frontend/src/index.css` (theme tokens only)
- Create: `frontend/src/lib/format.ts`, `frontend/src/lib/badges.ts`
- Test: `frontend/src/lib/format.test.ts`

**Interfaces:**

```ts
export function fmtUsd(n: number | null | undefined): string        // compact
export function fmtUsdFull(n: number | null | undefined): string    // "$1,234,567"
export function fmtPct(x: number | null | undefined, opts?: { signed?: boolean; digits?: number }): string
export function fmtShares(n: number | null | undefined): string
export function fmtDate(isoDate: string | null | undefined): string          // "2024-01-15" -> "Jan 15, 2024" (no TZ shift)
export function fmtDateET(isoDateTime: string | null | undefined): string    // -> "Jan 15, 2024 4:30 PM ET"
export function fmtRelative(isoDateTime: string, now?: Date): string          // "5m ago" | "3h ago" | "2d ago"
export function ratingLabel(score: number | null, confidence: "low" | "medium" | "high" | null): string
export const BADGE_LABELS: Record<string, string>; export const BADGE_HELP: Record<string, string>
export const PLAN_LABELS: Record<"flag" | "footnote" | "none", string | null>
```

- **Compact USD:**
  - At or above 1e9 → `$X.XXB`.
  - At or above 1e6 → `$X.XXM`.
  - At or above 1e3 → `$X.XK` (1 decimal).
  - Otherwise → `$X` (0 decimals).
  - Negatives get a leading `-`.
  - `null` → `—`.
- **`fmtPct`:** `signed` defaults to true, and `digits` to 1.
- **`BADGE_LABELS`:**
  - `cluster_buy` "Cluster buy"
  - `late_filing` "Late filing"
  - `first_buy_2y` "First buy in 2y"
  - `dip_buy` "Dip buy"
  - `big_stake` "Big stake"
  - `form144_matched` "Pre-announced (144)"
  - `top_exec` "CEO/CFO/President"
- **`BADGE_HELP`:** the exact rule text from spec 9.8, in plain words.
- **`PLAN_LABELS`:** `flag` "10b5-1 plan", `footnote` "10b5-1 (footnote)", `none` null.

- [ ] **Step 1: Write the failing tests:**

```ts
it("formats usd", () => {
  expect(fmtUsd(1234567)).toBe("$1.23M"); expect(fmtUsd(950)).toBe("$950")
  expect(fmtUsd(1_250_000_000)).toBe("$1.25B"); expect(fmtUsd(12_345)).toBe("$12.3K")
  expect(fmtUsd(-2_500_000)).toBe("-$2.50M"); expect(fmtUsd(null)).toBe("—")
  expect(fmtUsdFull(1234567)).toBe("$1,234,567")
})
it("formats pct", () => {
  expect(fmtPct(0.1234)).toBe("+12.3%"); expect(fmtPct(-0.05)).toBe("-5.0%"); expect(fmtPct(0)).toBe("0.0%")
  expect(fmtPct(0.1234, { signed: false })).toBe("12.3%"); expect(fmtPct(undefined)).toBe("—")
})
it("formats shares and dates", () => {
  expect(fmtShares(12000)).toBe("12,000"); expect(fmtShares(123.4567)).toBe("123.46")
  expect(fmtDate("2024-01-15")).toBe("Jan 15, 2024")
  expect(fmtDateET("2024-01-15T21:30:12Z")).toBe("Jan 15, 2024 4:30 PM ET")
  expect(fmtRelative("2024-01-15T21:25:00Z", new Date("2024-01-15T21:30:00Z"))).toBe("5m ago")
})
it("labels ratings", () => {
  expect(ratingLabel(78, "high")).toBe("78 · High"); expect(ratingLabel(null, null)).toBe("Not enough data yet")
})
```

- [ ] **Step 2:** Run `npm test -- format`. Expected: FAIL.

- [ ] **Step 3:** Implement, using `Intl.NumberFormat` and `Intl.DateTimeFormat` with `timeZone: "America/New_York"`. Set the theme tokens (`--pos`, `--neg`, `--muted`, the chart series colors) in `index.css` for both `:root` and `.dark`.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): design tokens, formatters and badge labels`.

---

### Task F2: Typed mock data and MSW handlers

**Files:**
- Create: `frontend/src/mocks/data/{feed,insiders,companies,funds,screener,compare,search,watchlists,health}.ts`
- Modify: `frontend/src/mocks/handlers.ts`
- Test: `frontend/src/mocks/handlers.test.ts`

**Interfaces:**
- Each data file exports objects typed with `Schema<"...">`, so they fail type-checking if the contract drifts.
- They mirror the backend seed world (plan 06): Acme 1000001, Globex 1000002 (formerly GBX), Doe Jane 2000001 (CEO, rated 78 · High), Roe Richard 2000002, New Person 2000005 (no stats), and Example Capital 3000001 (tracked). 3999999 is untracked.
- `handlers.ts` covers every path in the contract. They honor `cursor` (two pages for `/api/feed`), `direction`, `include_10b5_1`, `period` and `basis` where the tests below need it. `/api/funds/3999999/performance` returns 404 with the detail message. `/api/insiders/2000005` returns a header with a null rating.

- [ ] **Step 1: Write the failing tests:**
  - `/api/feed` returns page 1, then page 2 through the cursor.
  - `/api/insiders/2000005` has `rating.score === null`.
  - `/api/funds/3999999/performance` has status 404.
  - `/api/search?q=ac` has at least one company.

  Each test calls `fetch` against the MSW node server.

- [ ] **Step 2:** Run `npm test -- handlers`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass. Also run `npx tsc -b`. Expected: no type errors.

- [ ] **Step 5: Commit** with message `test(web): typed MSW mock data for every endpoint`.

---

### Task F3: Shared components and charts

**Files:**
- Create: the components listed under "Interfaces produced", plus `src/hooks/useUrlState.ts`
- Test: `frontend/src/components/components.test.tsx`, `frontend/src/components/charts/mapping.test.ts`

**Interfaces:**
- `DataTable<T>(props: { columns: ColumnDef<T, any>[]; data: T[]; getRowId: (r: T) => string; onEndReached?: () => void; isFetchingMore?: boolean; csvHref?: string; empty?: ReactNode; height?: number })`:
  - Sticky header, client-side sorting of the loaded rows, and row virtualization.
  - Calls `onEndReached` when the scroll comes within 200px of the bottom.
- `BadgeChip({ badge })` shows a tooltip with `BADGE_HELP`. `PlanChip({ flag })` renders nothing for `none`.
- `RatingPill({ rating })` shows `ratingLabel`. `ReturnCell({ value })` gets class `text-[--pos]` or `text-[--neg]`.
- `SecLink({ href, label? })`.
- `WindowsTable({ windows })` has rows YTD, 1Y, 3Y and 5Y and columns Return, vs SPY, vs QQQ, vs Sector, Vol and Max DD. The "vs" columns are `ret − ret_x`, and `—` when null.
- `ChangeChip({ change })` covers NEW, ADD, TRIM, EXIT and SAME.
- `BasisToggle` and `TenB51Toggle` read and write the URL params `basis` and `include_10b5_1`. `QuarterSelect({ periods })` reads and writes `period`.
- `useUrlState<T>(key, defaultValue, parse, serialize)` returns `[value, setValue]`.
- **`charts/mapping.ts`**, all pure:
  - `toCandles(bars)` gives `{time, open, high, low, close}`, sorted.
  - `toMarkers(markers)` gives lightweight-charts `SeriesMarker`s sorted by time:
    - `buy`: `arrowUp`, `belowBar`, `var(--pos)`, text `B`
    - `sell`: `arrowDown`, `aboveBar`, `var(--neg)`, `S`
    - `form144`: `circle`, `aboveBar`, amber, `144`
    - `stake`: `square`, `belowBar`, blue, `13D`
    - `cluster`: `circle`, `belowBar`, purple, `C`
  - `toLines(points, keys)`.
  - `topSlices(slices, n = 8)` aggregates the rest into `Other`.
- **Charts:**
  - `PriceChart({ bars, markers })`: `createChart` plus `chart.addSeries(CandlestickSeries)` and `createSeriesMarkers(series, toMarkers(markers))`. It resizes through a `ResizeObserver` and re-themes when `html.dark` toggles.
  - `EquityChart({ points, show })` uses `LineSeries` for nav, spy, qqq and sector.
  - `ValueChart({ points })` uses an `AreaSeries`.
  - `AllocationDonut({ slices })` uses a Recharts `PieChart`.

- [ ] **Step 1: Write the failing tests:**
  - `BadgeChip` shows `Cluster buy`.
  - `RatingPill` with a null score shows `Not enough data yet`.
  - `ReturnCell(-0.05)` renders `-5.0%` with the negative class.
  - `WindowsTable` renders `—` for null, and `+1.0%` for `ret=0.11, ret_spy=0.10` in "vs SPY".
  - The mapping tests check marker shapes and sort order, and that `topSlices` with 10 slices gives 9 entries, the last labelled `Other`.
  - `PriceChart` mounts without throwing when `lightweight-charts` is replaced by a stub via `vi.mock`.

- [ ] **Step 2:** Run `npm test -- components mapping`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): shared data components and charts`.

---

### Task F4: Live feed page

**Files:**
- Modify: `frontend/src/pages/FeedPage.tsx`
- Create: `frontend/src/pages/feed/{FeedFilters,FeedSummaryStrip,feedColumns}.tsx`
- Test: `frontend/src/pages/FeedPage.test.tsx`

**Behavior:**
- **Filters, all in the URL:**
  - form family (`3`, `4`, `5`, `144`, `13F`, `13D`, `13G`)
  - direction, roles (the `Role` values), sectors (the 11 sectors), badges
  - min and max value, min and max market cap
  - a "Hide 10b5-1" switch (default on, so it sends `include_10b5_1=false`)
  - trade and filed date ranges, and max lag days
- **Data:** `useInfiniteQuery` over `/api/feed`, with `getNextPageParam = last.next_cursor`. The first page refetches every 30 s.
- **New-filings pill:** when a refetch brings an accession newer than the top row, show a pill `N new filings` that scrolls to top and refreshes. Rows don't jump while you read.
- **Summary strip:** from `/api/feed/summary` (today): counts by form, top 3 buys, top 3 sells, clusters and late filings.
- **Rows:**
  - time (relative, with the exact ET time in a tooltip), form
  - company, linked to `/company/<ticker or cik>`
  - owners, linked to `/insider/<cik>` (or `/fund/<cik>` for 13F)
  - role, direction, value, price
  - badges, plan chip
  - `SecLink`
- **CSV:** a link to the same query with `format=csv`.

- [ ] **Step 1: Write the failing tests** (MSW):
  - `renders feed rows and summary`.
  - `hide 10b5-1 is on by default`: MSW captures a request with `include_10b5_1=false`.
  - `direction filter updates url and request`: clicking "Buys" puts `direction=buy` in the URL and in the next request.
  - `loads next page on scroll end`: `onEndReached` triggers a request with a `cursor`.
  - `empty state`: a handler returning 0 items shows the text `No filings match these filters`.

- [ ] **Step 2:** Run `npm test -- FeedPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): live feed page`.

---

### Task F5: Insider profile page

**Files:**
- Modify: `frontend/src/pages/InsiderPage.tsx`
- Create: `frontend/src/pages/insider/{InsiderHeader,DecisionsTab,TransactionsTab,HoldingsTab,Form144Tab}.tsx`, `frontend/src/hooks/useWatch.ts`
- Test: `frontend/src/pages/InsiderPage.test.tsx`

**Behavior:**
- **Header:**
  - name, and roles by company (linked)
  - `RatingPill`, Avg ROI (6m, vs SPY), hit rate, average lag and lag cost
  - `BasisToggle` and `TenB51Toggle`
  - a watch button (`useWatch("insider", cik)`: adds to the first watchlist, creating "My watchlist" if none exists)
  - a fund cross-link when `fund_cik` is set
- **Performance:** `EquityChart` plus `WindowsTable` from `/performance`.
- **Tabs, in the URL `tab`:**
  - Decisions: date, company, direction, value, stake change, badges, and the 1m/3m/6m/12m excess returns for the current basis.
  - Transactions: all codes, with a "show superseded" toggle.
  - Holdings: a table plus `AllocationDonut` by sector.
  - Form 144.

- [ ] **Step 1: Write the failing tests** (MSW):
  - `renders header metrics` (2000001 shows `78 · High`).
  - `renders not-enough-data state`: 2000005 shows `Not enough data yet`, and the Avg ROI shows `—`.
  - `basis toggle refetches with basis=executed`.
  - `tabs switch via url`.
  - `watch button creates default watchlist then adds item`: MSW records the POST `/api/watchlists` and then the POST to items.

- [ ] **Step 2:** Run `npm test -- InsiderPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): insider profile page`.

---

### Task F6: Company page

**Files:**
- Modify: `frontend/src/pages/CompanyPage.tsx`
- Create: `frontend/src/pages/company/{CompanyHeader,InsidersTab,InstitutionsTab,StakesTab,CompanyForm144Tab}.tsx`
- Test: `frontend/src/pages/CompanyPage.test.tsx`

**Behavior:**
- **Header:**
  - name, current ticker, `formerly GBX` when there are former tickers
  - sector, market cap, latest close with its date
  - net buying chips for 3m, 6m and 12m (net USD, buyers and sellers)
  - a watch button
- **Chart:** `PriceChart` with markers for the last 3 years.
- **Tabs:**
  - Insiders (roster).
  - Institutions: a `QuarterSelect` over `periods_available`, rows with `ChangeChip`, and totals with holders, new and exit counts.
  - Stakes: 13D/13G, with activist emphasis on 13D.
  - Form 144.

- [ ] **Step 1: Write the failing tests:**
  - `shows former ticker`: `/company/GBX` renders `formerly GBX` and a heading `Globex Inc`.
  - `quarter select requests period`: choosing `2024-03-31` sends `period=2024-03-31`.
  - `change chips render`: the NEW and EXIT labels are visible.
  - `unknown company shows not found`: a 404 renders `Company not found`.

- [ ] **Step 2:** Run `npm test -- CompanyPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): company page`.

---

### Task F7: Fund page

**Files:**
- Modify: `frontend/src/pages/FundPage.tsx`
- Create: `frontend/src/pages/fund/{FundHeader,FundHoldings,FundPerformance}.tsx`
- Test: `frontend/src/pages/FundPage.test.tsx`

**Behavior:**
- **Header:** name, a tracked badge, `ValueChart` of value history, latest positions, `RatingPill`, coverage % (`Priced coverage 92%`), and an insider cross-link.
- **Performance:** `EquityChart` plus `WindowsTable` for the basis in the URL. A 404 shows `Performance is available for tracked funds only`.
- **Holdings:**
  - `QuarterSelect`.
  - A table (security, ticker, value, weight, prior weight, change chip, shares change %, sector) with ★ marking high-conviction rows.
  - A separate "Exited this quarter" section.
  - A sector donut, and effective N and top-5 weight stats.

- [ ] **Step 1: Write the failing tests:**
  - `renders holdings and exits separately`.
  - `untracked fund message`: `/fund/3999999` shows `Performance is available for tracked funds only`.
  - `high conviction star shown`.

- [ ] **Step 2:** Run `npm test -- FundPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): fund page`.

---

### Task F8: Screener

**Files:**
- Modify: `frontend/src/pages/ScreenerPage.tsx`
- Create: `frontend/src/pages/screener/{InsiderScreener,FundScreener,ScreenerFilters}.tsx`
- Test: `frontend/src/pages/ScreenerPage.test.tsx`

**Behavior:**
- Tabs for Insiders and Funds (`tab`), with filters matching the endpoint's parameters.
- Clicking a column header sets `sort` and `order` in the URL (server sort).
- "Load more" pages through the cursor, and a CSV link is provided.
- Rows link to the profiles.

- [ ] **Step 1: Write the failing tests:**
  - `sort click sends sort and order`: clicking "Avg ROI" sends `sort=avg_roi_6m&order=desc`, and clicking again sends `asc`.
  - `role filter sends roles=CEO`.
  - `funds tab requests /api/screener/funds`.

- [ ] **Step 2:** Run `npm test -- ScreenerPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): insider and fund screener`.

---

### Task F9: Compare

**Files:**
- Modify: `frontend/src/pages/ComparePage.tsx`
- Test: `frontend/src/pages/ComparePage.test.tsx`

**Behavior:**
- The URL holds `ids=insider:2000001,fund:3000001`, with at most 4.
- An "Add" picker reuses the search API. It's disabled at 4, with the hint `Up to 4 profiles`.
- One chip per profile, each removable.
- An overlaid `EquityChart` showing nav per profile, a side-by-side stats table (rating, Avg ROI, hit rate, and the windows), and one allocation donut per profile.

- [ ] **Step 1: Write the failing tests:**
  - `requests compare with ids from url`.
  - `removing a chip updates url`.
  - `add disabled at four`.

- [ ] **Step 2:** Run `npm test -- ComparePage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): compare page`.

---

### Task F10: Watchlists

**Files:**
- Modify: `frontend/src/pages/WatchlistsPage.tsx`
- Test: `frontend/src/pages/WatchlistsPage.test.tsx`

**Behavior:**
- The page lists watchlists, with create (inline name input) and delete (with a confirm dialog).
- The selected watchlist (`id` in the URL) shows its items, each linked and removable, plus an activity feed that reuses the feed columns and paginates.

- [ ] **Step 1: Write the failing tests:**
  - `create posts name`.
  - `delete asks confirmation then sends DELETE`.
  - `activity renders feed rows for selected list`.

- [ ] **Step 2:** Run `npm test -- WatchlistsPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): watchlists page`.

---

### Task F11: Data health page

**Files:**
- Modify: `frontend/src/pages/HealthPage.tsx`
- Test: `frontend/src/pages/HealthPage.test.tsx`

**Behavior:**
- **Status banner:** `ok` shows `All systems normal`, `warn` shows `Needs attention`, and `error` shows `Problem detected`. When `sec_blocked_until` is set, the banner adds `SEC paused requests until <time ET>`.
- **Jobs:** a table of the jobs.
- **Feed delay:** p50 and p95 in seconds, and the last filing seen (relative).
- **Parse errors:** a table with a **Reparse** button that POSTs `/api/jobs` with `{kind: "reparse", params: {accessions: [acc]}}`.
- **Backfill:** progress bars, and a **Start full backfill** button (a confirm dialog, then a POST with `{kind: "backfill_all"}`).
- **Coverage:** the coverage percentages.
- The page refreshes every 30 s.

- [ ] **Step 1: Write the failing tests:**
  - `status banner text per status`: three MSW variants.
  - `reparse posts accession`.
  - `start backfill requires confirmation`.

- [ ] **Step 2:** Run `npm test -- HealthPage`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): data health page`.

---

### Task F12: ⌘K search palette

**Files:**
- Create: `frontend/src/components/search/SearchPalette.tsx`
- Modify: `frontend/src/components/layout/AppShell.tsx` (wire the trigger and the ⌘K/Ctrl+K shortcut)
- Test: `frontend/src/components/search/SearchPalette.test.tsx`

**Behavior:**
- It uses the shadcn `CommandDialog`.
- It queries `/api/search?q=` once the input has at least 2 characters, debounced by 200 ms.
- Results are grouped into Companies, Insiders and Funds, each with a subtitle.
- Enter navigates: companies go to `/company/<ticker or cik>`, insiders to `/insider/<cik>`, and funds to `/fund/<cik>`.
- Esc closes it.

- [ ] **Step 1: Write the failing tests:**
  - `opens with keyboard shortcut`.
  - `debounced search shows groups`: typing `ac` shows the heading `Companies` and `Acme Corp`.
  - `enter navigates to company`.

- [ ] **Step 2:** Run `npm test -- SearchPalette`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `npm test`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(web): command-K search palette`.

---

### Task F13: Browser smoke test (mock mode)

**Files:**
- Create: `frontend/e2e/smoke.spec.ts`
- Modify: `frontend/playwright.config.ts`: `webServer: { command: "npm run dev -- --port 5174", env: { VITE_MOCK: "1" }, url: "http://127.0.0.1:5174" }`, overridable by env `E2E_BASE_URL` for integration.

**Test:** for each route (`/`, `/insider/2000001`, `/company/ACME`, `/fund/3000001`, `/screener`, `/compare?ids=insider:2000001`, `/watchlists`, `/health`):
- a visible `h1` exists;
- no `console.error` fires (collected through `page.on("console")`);
- the footer text is present.

It also checks that at a 390×844 viewport, `document.documentElement.scrollWidth <= 390` on `/` and `/insider/2000001`.

- [ ] **Step 1:** Write the spec. Run `npx playwright install chromium`, then `npx playwright test`. Expected: FAIL at first for any page that still has issues, then fix.

- [ ] **Step 2:** Run `npx playwright test`. Expected: 8 routes pass, plus the 2 mobile checks.

- [ ] **Step 3:** Run `npm test && npm run build && npm run lint`. Expected: all green.

- [ ] **Step 4: Commit** with message `test(web): Playwright smoke test for every route (mock mode)`.
