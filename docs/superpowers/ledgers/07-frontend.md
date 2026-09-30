# SDD ledger — plan: docs/superpowers/plans/2026-09-27-sec-dashboard/07-frontend.md

Spec: docs/superpowers/specs/2026-09-27-sec-dashboard-design.md (read: §9.8, §10, §11, all).
Executor: inline (executing-plans), no subagents allowed (user cap). Branch ws/f-frontend from tag foundation (4654e30).
Baseline at foundation: npm test 2/2, build exit 0, lint exit 0.
Tooling note: plan headings are "Task F<n>", so task-brief/task-start (numeric-only regex) are replaced by a manual awk extract; task-done is called with N=F<n>.

## Pre-flight (shared interfaces)
| Producer → Consumer | Produces vs consumes | Finding |
|---|---|---|
| F1 format/badges → F3 chips, pills, cells, all pages | fmtPct/ratingLabel/BADGE_* | consistent |
| F2 mocks → F4–F13 tests | seed-world ids, cursor paging, 404s | F7 needs a /api/funds/3999999 header (untracked) as well as the 404 performance; F13 needs /company/ACME (case-insensitive ticker) |
| F3 ReturnCell → pages | plan: class `text-[--pos]`/`text-[--neg]` | CONFLICT: Tailwind 4 no longer treats `[--x]` as var(--x); the class would emit invalid CSS. See Ruling P1 |
| F3 toMarkers → PriceChart | plan: marker color `var(--pos)` | CONFLICT: lightweight-charts draws on canvas; canvas cannot resolve var(). See Ruling P2 |
| F3 DataTable (client sort) → F8 screener (server sort via URL) | DataTable sorts loaded rows; screener needs manual sort | additive props (sorting/onSortingChange/manualSorting). See Ruling P3 |
| F3 DataTable onEndReached → F4 feed, F10 activity | infinite paging | consistent; also render a "Load more" button when onEndReached is set (non-scrollable first page) |
| F4 feedColumns → F10 activity | column defs over FeedItemOut | consistent (activity returns FeedPage) |
| F5 useWatch → F6 company watch button | useWatch(kind, cik) | consistent |
| F3 BasisToggle/TenB51Toggle → F5/F7/F8/F9 | URL params basis / include_10b5_1 | consistent; default filed / false |

Ruling P1: ReturnCell colors use Tailwind 4 theme utilities `text-pos`/`text-neg` (backed by --pos/--neg via @theme inline) instead of `text-[--pos]` — Tailwind 4 changed CSS-var shorthand to `(--x)`, so the literal plan class would render uncolored — cost if wrong: a consumer asserting the literal class name (none outside this workstream).
Ruling P2: toMarkers(markers, colors?) takes a resolved color palette (defaults are concrete hex values); PriceChart passes colors read from CSS tokens at render time — canvas cannot paint `var(--pos)` — cost if wrong: none functionally; signature is a superset of the plan's.
Ruling P3: DataTable gains optional controlled-sort props (sorting, onSortingChange, manualSorting) so the screener can sort server-side via URL while other tables keep client-side sorting — cost if wrong: none (additive).

## Design plan (frontend-design + dataviz, before F1)
Subject: SEC insider/institutional filings; audience: one self-directed investor (public later); job: triage the live filing stream, then judge the credibility of the person behind a trade (returns measured from the filing time).
Color light/dark: plane #F4F6F9/#0C121B, surface #FFFFFF/#131A24, ink #162033/#E3E9F2, ink-2 #46536A/#AAB5C5, muted #667085/#8792A3, rule #DFE4EB/#243044, accent #2451C7/#8AA9FF (links+focus only), pos #0A7A43/#3FBF7F, neg #C42B2B/#FF7B72 (all text >=4.5:1 on both planes, checked with the dataviz contrast()).
Chart categorical: dataviz default order, validated vs my surfaces: light PASS (contrast WARN slots 3-5 -> direct labels / table twin required), dark PASS all.
Type: system sans only (local app, no network fonts, dataviz rule); 400/500/600; 11/12/13/14/16/20/24; tabular-nums in tables/axes, proportional on KPI figures; sentence case, no all-caps eyebrows, no arrow-suffixed links.
Layout: sticky app bar -> title row (h1 left, page controls right) -> one filter row -> content; left aligned; hairline-bordered panels (6px radius, no shadows); tables scroll inside their own region.
Principles: (1) filing time is the clock: acceptance time leads feed rows, basis defaults to "From filing"; (2) direction is the one loud signal: 3px buy/sell margin rule on trade rows + signed colored returns; (3) noise recedes: non-discretionary rows in secondary ink; (4) every SEC number links to its filing.
Self-review: navy+blue-everything reads as the fintech-terminal default -> revised: accent limited to links/focus, primary buttons use ink, identity carried by principles 2-3 instead of hue.
Task F1: complete (commits 4654e30..aaaef6a, tests: npm test →    Duration  1.59s (transform 72ms, setup 461ms, import 292ms, tests 85ms, environment 1.79s))
F1 counts: vitest 10/10 (format 8 + App 2), build 0, lint 0

## Task F2 (picked up mid-WIP: domain.ts, state.ts, handlers.test.ts and mocks/data/{world,insiders,companies,funds,feed,series}.ts already drafted; handlers.ts was still the foundation's empty stub)

Ruling F2.1: the untracked fund (3999999) is renamed "Small Fry Advisors" (the WIP draft had
it as "Quiet Harbor Advisors") — the task brief says to match ws/e-api's seed.py names
exactly, and that file names SMALL_FUND = "Small Fry Advisors" — cost if wrong: none, no test
asserts either string; this is a pure fidelity fix to the seed world.

Ruling F2.2: insider ratings (Doe 78 · High, Roe 54 · Medium) are fixed per profile,
independent of `basis`/`include_10b5_1` — the backend seed varies Doe's rating by
basis×toggle (80/75/78/72), but the plan's own F5 step 1 text hardcodes "2000001 shows 78 ·
High" with no toggle qualifier. A static rating trivially satisfies that literal assertion
under any toggle state; matching the backend's 4-way matrix instead would make the header
number toggle-dependent and risk contradicting the plan's own wording — cost if wrong: F5
would need one extra fixture number per basis/toggle combination (a small, local change).

Ruling F2.3: fund rating/avg_roi_6m/hit_rate now come from a `profile_stats`-shaped table
(`fundRating`/`fundStats` in mocks/data/funds.ts) keyed by CIK regardless of `is_tracked`,
while `windows`/`coverage_pct` (and the whole `/performance` endpoint) stay gated on tracked
status. This mirrors the backend seed's own comment ("Small Fry ... has its own profile_stats
row ... so the screener's tracked_only filter has something real to exclude") — without it,
`/api/screener/funds?tracked_only=false` would have nothing to show for the untracked fund —
cost if wrong: F8's fund screener would need its own rating source for untracked rows.

Ruling F2.4: the WIP's `handlers.test.ts` had a "covers every path" sweep that called
`resetMockState()` before every single request, including ones using a hardcoded
`watchlist_id: "1"`. Mock state starts with zero watchlists on purpose (see below), so that
sweep could never have passed. Rewrote it to create one watchlist up front, reuse its real id
for every `{watchlist_id}` path, and skip the two destructive DELETEs in the generic sweep
(covered instead by one small dedicated test) — cost if wrong: n/a, this is test-only code
under this workstream's ownership.

Ruling F2.5: mock state starts with **zero** watchlists (no pre-seeded "My watchlist"), even
though that would have made ruling F2.4's sweep simpler. The plan's F5 test
("watch button creates default watchlist then adds item: MSW records the POST
/api/watchlists and then the POST to items") requires that first-use flow to actually create
one — a pre-seeded default would make useWatch skip the creation call and fail that test —
cost if wrong: F5 would need to delete a pre-seeded row instead of asserting a POST, i.e. the
opposite of what its step-1 text says.

Ruling F2.6: `src/test/setup.ts` now calls `server.listen({onUnhandledRequest:"error"})` as a
top-level side effect instead of inside `beforeAll`. openapi-fetch's `createClient` (in the
read-only `src/api/client.ts`) defaults its internal `fetch` to `globalThis.fetch` evaluated
at call time, i.e. when `client.ts` is first imported — which happens while the test file's
module graph loads, before any `beforeAll` callback runs. With `server.listen()` inside
`beforeAll`, the singleton `api` client permanently captured the pre-MSW `fetch` and every
`api.GET(...)` call hit the real network (`ECONNREFUSED`) instead of MSW. Moving `.listen()`
to setup.ts's top level (setup files finish evaluating before a test file's own imports run)
patches `globalThis.fetch` first. `client.ts` itself was not touched — this is test
infrastructure, not a contract bug — cost if wrong: any test that uses the typed `api` client
(rather than raw `fetch`) would silently try the real network and fail with a connection
error; tests using raw `fetch` are unaffected either way.

F2 mock data additions beyond the WIP draft: `mocks/data/{search,compare,screener,health}.ts`
(the plan's suggested split — feed/insiders/companies/funds/screener/compare/search/
watchlists/health — was followed loosely; watchlists live in `state.ts` since they're
stateful, not static fixtures). `handlers.ts` now covers all 31 path×method combinations in
the contract, keyset-style cursor pagination is a base64'd offset (opaque to callers, as the
spec requires), and CSV export is a generic dotted-key flattener used by every list endpoint
that has a `format` param.

F2 counts: vitest 22/22 (10 from F1 + 12 handlers), build 0, lint 0, tsc -b 0.
Task 2: complete (commits 3047c0c..6f716b6, tests: npm --prefix frontend test →    Duration  1.74s (transform 261ms, setup 1.36s, import 281ms, tests 149ms, environment 2.50s))

## Task F3 (shared components and charts)

Ruling F3.1: `DataTable`'s columns prop is `ColumnDef<T>[]` (TanStack's 2nd generic defaults
to `unknown`), not the plan's literal `ColumnDef<T, any>[]` — this project's eslint config
(`typescript-eslint` recommended, this version) treats `@typescript-eslint/no-explicit-any` as
an **error**, not a warning, so the literal plan signature fails `npm run lint`. `unknown` is
behavior-equivalent for every current caller (none narrow the cell-value generic) — cost if
wrong: a future column definition that genuinely needs a wider value type adds its own cast at
the call site, same as it would with `any`.

Ruling F3.2: two jsdom-only shims added to `src/test/setup.ts`, project-wide (not per-test):
1. A no-op `ResizeObserver` polyfill — lightweight-charts' resize handling, Recharts'
   `ResponsiveContainer` and some Radix primitives all call `new ResizeObserver(...)`, which
   jsdom doesn't implement at all (throws `ReferenceError` otherwise).
2. `HTMLElement.prototype.offsetWidth`/`offsetHeight` overridden to a fixed 1024×768. jsdom
   never computes layout, so both are always 0; `@tanstack/react-virtual` sizes its viewport
   from exactly those two properties (confirmed by reading virtual-core's `getRect`), so with
   the jsdom default every `DataTable` rendered in a test showed zero rows regardless of
   `data.length`. A test needing different scroll metrics overrides them per-element with
   `Object.defineProperty` (see `DataTable > calls onEndReached`), which takes precedence over
   the prototype default. Cost if wrong: any test asserting on table row count silently sees
   zero rows and fails loudly (not a silent pass), so this would have been caught immediately.

Ruling F3.3: `EquityChart` assigns nav/spy/qqq/sector to `--series-1..4` in a **fixed** order,
never reassigned by which series a given page happens to show (dataviz rule: color follows
the entity, never its rank) — and always renders a text legend (colored swatch + plain-ink
label) once there's more than one series. This satisfies the design-review self-check already
logged under "Design plan" above (light-surface contrast WARN on categorical slots 3-5 needs
"direct labels / table twin"): a WindowsTable already accompanies every EquityChart per the
plan, and the legend adds the direct-label half even before the table twin renders — cost if
wrong: none functionally (WindowsTable alone would still satisfy the WARN), it's a UX
improvement.

Ruling F3.4: `toMarkers`/`PriceChart` marker `id` is set to the marker's `ref` (accession or
`cluster:<cik>:<date>`), which the plan doesn't ask for. Cost if wrong: none — it's additive
and unused until a later task wires marker clicks to navigation (spec principle 4, every SEC
number links to its filing), at which point it's already there.

F3 counts: vitest 54/54 (22 F2 + 7 mapping + 25 components), build 0, lint 0 (1 pre-existing
react-hooks/incompatible-library warning from TanStack Table's `useReactTable`, not an error),
tsc -b 0.
Task 3: complete (commits 6f716b6..8241041, tests: npm --prefix frontend test →    Duration  1.91s (transform 487ms, setup 1.83s, import 792ms, tests 287ms, environment 3.78s))

## Task F4 (live feed page)

Ruling F4.1 (**affects F5-F13**): a page's `ColumnDef<T>[]` array built with
`createColumnHelper<T>().accessor(...)` cannot be assigned — even via an explicit variable
annotation — directly to DataTable's `columns: ColumnDef<T>[]` prop type in this TanStack
Table version (8.21.3): tsc reports "Two different types with this name exist, but they are
unrelated" (a generic-variance false positive from erasing each column's own inferred TValue
down to DataTable's homogeneous `unknown`). Confirmed with a clean `tsc -b --force` (not a
stale `.tsbuildinfo`) and by isolating the failure to the exact erasure step. Fix: build the
array as a local `const columns = [...]` (no annotation — let each `.accessor()` call infer
its own TValue), then export `as unknown as ColumnDef<T>[]` (double-cast through `unknown`,
never `any`, so `no-explicit-any` stays clean). See `src/pages/feed/feedColumns.tsx` for the
pattern. Cost if wrong: purely a compile-time nuisance — the runtime objects are ordinary
`ColumnDef`s either way — but every future page hits this the first time it types a shared
column array, so it's worth reusing the pattern rather than rediscovering it.

Ruling F4.2: `DataTable` gained one more additive prop, `rowClassName?: (row: T) => string |
undefined`, so a page can style a whole row from its data (here, the spec's "direction is the
one loud signal" 3px buy/sell left-border) without DataTable knowing what "direction" means.
Backward compatible with every F3 caller — cost if wrong: none, opt-in.

Ruling F4.3: multi-select URL filters (forms/roles/sectors/badges) use one comma-joined param
per filter (`?roles=CEO,CFO`) via a new `useUrlListState` hook added to `hooks/useUrlState.ts`,
translated into the API's repeated-key array shape only when building the actual request. The
API contract itself is untouched (still `roles=CEO&roles=CFO` on the wire) — this is purely
this app's own URL convention. F8's screener has the same kind of multi-selects (roles,
sectors, confidence, risk); reusing `useUrlListState` there keeps the convention consistent —
cost if wrong: a differently-shaped screener URL is a cosmetic inconsistency, not a bug.

Ruling F4.4: the "N new filings" pill polls a *separate* `useQuery` (its own cache key), not
an interval-refetch of the `useInfiniteQuery` that backs the visible rows. The spec text is
explicit that rows must not jump while someone is reading, so the displayed list only changes
on an explicit click (which calls `feed.refetch()` and scrolls to top). This path has no
automated test — it's not in the plan's required F4 test list, and reliably driving a 30s
`refetchInterval` under fake timers plus MSW plus React Query's own scheduling was judged more
risk than the coverage was worth for this batch. Flagged in the handoff for whoever adds it —
cost if wrong: a cosmetic feature (a pill that would appear late or not at all) ships
unverified by CI; nothing it touches is shared state other pages depend on.

Ruling F4.5: everything the plan's Behavior section lists beyond direction and 10b5-1 (form
family, roles, sectors, badges, value/market-cap ranges, trade/filed date ranges, max lag
days) lives behind one "Filters" Sheet instead of a second filter row, to honor the layout
plan's "one filter row" while still implementing every listed filter — cost if wrong: none,
it's a progressive-disclosure UI choice over already-correct URL/query wiring.

F4 counts: vitest 59/59 (54 from F1-F3 + 5 FeedPage), build 0, lint 0 (same pre-existing
react-hooks/incompatible-library warning), tsc -b 0.
Task 4: complete (commits 8241041..25603f1, tests: npm --prefix frontend test →    Duration  2.10s (transform 692ms, setup 2.65s, import 1.26s, tests 964ms, environment 4.68s))
