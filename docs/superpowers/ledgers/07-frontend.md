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

## Task F5 (insider profile page)

New shared, non-produced-interface helpers added (small enough not to warrant their own
ledger heading, but used by F6/F7 too): `src/lib/httpError.ts` (`HttpError`, `required(data,
response)`, `isNotFound(error)` — openapi-fetch decides `data` vs `error` by `response.ok`, not
by which status codes a path's schema documents, so an undocumented 404 like
`/api/companies/{ref}` or `/api/funds/{cik}/performance` for an untracked fund still needs a
real status to branch on) and `src/lib/queryParams.ts` (`basisParam`/`includeParam`, reading the
same `basis`/`include_10b5_1` URL keys `BasisToggle`/`TenB51Toggle` already own, so a page's
fetch always agrees with what its own toggles show).

Ruling F5.1: every profile/entity header's `<h1>` renders the bare name only (ticker, rating,
stats, badges all live in sibling elements), never inline text appended to the heading — the
plan's own test wording for F6 ("a heading `Globex Inc`") and by the same pattern F5/F7 need the
heading's accessible name to be exactly the entity name; appending anything inline (e.g. a
ticker) would extend that accessible name and break an exact-string heading query — cost if
wrong: a heading query in a later task needs a regex/substring matcher instead of an exact
string, and the header's own tests here would need rewriting.

Ruling F5.2: this workstream's own F2-F4 handoff note ("Radix ToggleGroup items appear as plain
buttons... query with getByRole('button', ...) or getByText, not 'radio'") is only half right —
rendering `BasisToggle` and reading the accessible-roles dump on a failed query shows Radix's
single-select `ToggleGroup` (`type="single"`) actually sets `role=radiogroup`/`role=radio` in
this radix-ui version. `getByRole("button", ...)` fails outright (confirmed: it was the first
failure here). Tests here use `getByText` instead, matching the pattern F4's own FeedPage.test
already used for the same component (`screen.getByText("Buys")`) — cost if wrong: a
`getByRole("button", ...)` query on any BasisToggle/TenB51Toggle item in a later task fails
immediately; `getByRole("radio", ...)` would also work but `getByText` needs no role knowledge.

F5 counts: vitest 64/64 (59 from F1-F4 + 5 InsiderPage), build 0, lint 0 (same pre-existing
react-hooks/incompatible-library warning), tsc -b 0.
Task 5: complete (commits 25603f1..9a68ada, tests: npm --prefix frontend test →    Duration  5.27s (transform 1.46s, setup 7.12s, import 5.26s, tests 2.19s, environment 14.30s))

## Task F6 (company page)

Ruling F6.1: added jsdom shims to `src/test/setup.ts`, project-wide (same rationale/pattern as
F3's Ruling F3.2): `Element.prototype.hasPointerCapture`/`setPointerCapture`/
`releasePointerCapture`/`scrollIntoView`. jsdom (checked: v30.1.1, confirmed absent by grepping
its source) implements none of these; Radix's `Select` (`QuarterSelect`'s base, first exercised
by an interactive test in this task) calls them from its pointer-down handling and throws
"is not a function" the instant a test opens the dropdown otherwise — cost if wrong: any test
that opens a Select (here or in later tasks) fails immediately with that TypeError, so it would
have been caught right away.

Ruling F6.2 (see the comment on `InstitutionsTab`): the Institutions tab's totals row always
renders a `ChangeChip change="NEW"` and `ChangeChip change="EXIT"` next to their counts, even
when a count is 0, rather than only showing per-row chips — `InstitutionsOut.rows` only lists
*current* holders (exits are the count `exit_count`, with no row detail, unlike
`FundHoldingsOut`'s separate `exits` array), so no single company/period in the seed world is
guaranteed to have an EXIT-changed row to show inline next to a NEW one, but the plan's own test
("change chips render": the NEW and EXIT labels are visible) needs both visible from one render.
Reusing the row-level chip vocabulary for the summary counts satisfies this deterministically —
cost if wrong: purely cosmetic (plain-text counts instead of chips); no other code depends on it.

Ruling F6.3: every `useQuery` that can 404 for an expected, non-transient reason (an unknown
company ref, later an untracked fund's performance in F7) passes the new
`retry: retryUnlessNotFound` (added to `src/lib/httpError.ts` alongside F5's `HttpError`/
`required`/`isNotFound`) instead of falling through to the app's default `retry: 1`. Found via a
real test failure: the default retry adds a ~1s backoff delay before a 404 settles to the
query's `error` state, which blew past `findByText`'s default 1000ms timeout and made
"unknown company shows not found" flaky/failing even though the UI was otherwise correct —
retrying a 404 can't change the outcome anyway. Applied retroactively to F5's insider header
query too, for the same latent reason (untested there, but the same shape of bug). Cost if
wrong: none, it only removes a pointless retry on a definitive error.

Note (not a ruling, a correction to this same task's own work): the first draft of
`CompanyHeader` put the ticker and "formerly GBX" note in one `<p>` as adjacent text/fragment
children. `screen.getByText("formerly GBX")` failed with testing-library's "text is broken up by
multiple elements" hint even though visually it looked like one line — the ticker text before it
made the paragraph's own `textContent` (the match target) longer than just "formerly GBX". Every
header in this workstream now gives a fact its own leaf element when a test (here, or plausibly
a later one) might match it by exact text.

F6 counts: vitest 68/68 (64 from F1-F5 + 4 CompanyPage), build 0, lint 0 (same pre-existing
react-hooks/incompatible-library warning), tsc -b 0.
Task 6: complete (commits 9a68ada..cf3b455, tests: npm --prefix frontend test →    Duration  5.99s (transform 1.79s, setup 7.28s, import 7.35s, tests 2.91s, environment 20.82s))

## Task F7 (fund page)

No new rulings: F7 reused F5/F6's established patterns directly (bare-name `<h1>` per F5.1,
`retryUnlessNotFound` on the header and performance queries per F6.3 — the performance query is
exactly the review-focus "untracked fund" 404 case that ruling was written for) and all three
tests (renders holdings and exits separately, untracked fund message, high conviction star
shown) passed on the first implementation without needing a test rewrite.

F7 counts: vitest 71/71 (68 from F1-F6 + 3 FundPage), build 0, lint 0 (same pre-existing
react-hooks/incompatible-library warning), tsc -b 0.
Task 7: complete (commits cf3b455..54797e1, tests: npm --prefix frontend test →    Duration  4.57s (transform 2.24s, setup 7.43s, import 6.71s, tests 2.80s, environment 14.77s))

## Continuation 2026-09-30 (Codex)
Task F8: Ruling: use up to three subagents concurrently, with one frontend writer and read-only reviewers — the user explicitly authorized up to three agents, superseding the earlier no-subagent note — cost if wrong: coordination overhead only; task ownership stays unchanged.
Task F8: Ruling: preserve live progress ledgers and copy them into docs at integration — repository instructions require durable task/ruling history — cost if wrong: retained small documentation files.

| Pre-flight | Interface or consistency check | Result |
|---|---|---|
| F8 → F9 | basis/include toggles and fund summary semantics | Reuse URL hooks; fund summary ROI is quarterly, never labeled 6m. |
| F8 → DataTable | controlled sorting and pagination | Existing manualSorting props support server sorting; cursor belongs to the selected filters. |
| F9 → EquityChart | overlay named profile curves | Existing chart supports lines; verify before implementation. |
| F10 → F4/useWatch | feed columns and watchlist query cache | Reuse feed columns; invalidate the shared watchlists query. |
| F11 → API | HealthOut and POST jobs | Frozen contract supports all required controls. |
| F12 → AppShell | trigger, keyboard events, CommandDialog | Existing trigger is unwired; connect once at shell level. |
| F13 → F8–F12 | route coverage, mobile, console errors | Run after every page exists; browser failures must be fixed. |
| F8 | specified files, tests, endpoint filters | Consistent. |
| F9 | URL ids, picker, chart and comparison tests | Consistent; use quarterly labels for funds. |
| F10 | CRUD confirmations, URL id, activity tests | Consistent. |
| F11 | status, reparse, confirmation tests | Consistent. |
| F12 | debounce, grouped results, keyboard tests | Consistent. |
| F13 | e2e file outside src | Explicit plan ownership includes frontend/e2e and playwright.config.ts for this task. |
Task F8: Ruling: parent implemented F8 after the assigned implementer hit an account usage limit; read-only integration agent reviewed the change — continuation remained authorized — cost if wrong: review independence reduced, mitigated by endpoint and behavior checks.
Task F8: Ruling: F10 and F11 may be implemented concurrently in disjoint page/test files; parent owns shared files and all commits — these pages have no dependency on F9 and user authorized three agents — cost if wrong: transient full-suite failures while RED tests exist; commits wait for GREEN.
Task F8: Ruling: expose sorting only for server-supported keys until integration extends the whitelist to every display column — unsupported keys silently fall back to rating in current backend — cost if wrong: temporarily limited header sorting; integration must reconcile with spec.
Task F8: Ruling: reject fractional/out-of-range ratings and nonpositive/fractional decision counts locally — real API expects integers, MSW does not validate — cost if wrong: narrower invalid-input behavior only.
Task 8: complete (commits 54797e1..5e733d2, tests: npm test -- ScreenerPage → 6 passed; npm test → 77 passed; npm run build && npm run lint → exit 0, existing DataTable compiler warning and bundle-size warning)
Task F9: Ruling: add named comparison series to EquityChart while preserving its existing points API — the fixed nav/benchmark interface cannot overlay up to four profiles — cost if wrong: additive shared-chart maintenance; component tests and browser smoke protect existing profiles.
Task F9: Ruling: keep identity-stable curve colors and use dashed fund curves versus solid insider curves, mirrored in the legend — independent review found the default CIKs collide in the eight-color palette — cost if wrong: categorical dash styling adds one visual distinction; regression confirms two profile series are drawn with distinct styles.
Task 9: complete (commits 5e733d2..6af117b, tests: npm test -- ComparePage → 4 passed after initial RED 4 failures and review RED for colliding styles; npm test → 107 passed; npm run build && npm run lint → exit 0)
Task 10: complete (commits 6af117b..78ed6ec, tests: npm test -- WatchlistsPage → 12 passed after initial RED 11 failures and pending-pagination RED; npm test → 107 passed; npm run build && npm run lint → exit 0)
Task 11: complete (commits 78ed6ec..69e27f5, tests: npm test -- HealthPage → 14 passed after initial RED 14 failures and reparse-retry RED; npm test → 107 passed; npm run build && npm run lint → exit 0)
Task F10: Ruling: a missing URL id selects the first list and writes its id with replace;
an explicit unknown id shows a not-found state, keeping list navigation available — views
must be shareable while stale saved URLs must not silently show another list — cost if wrong:
one URL default-selection policy may need adjusting; no API changes.

Task F10: Ruling: after deleting the selected list, select the first surviving list;
remove id when no lists remain, and preserve unrelated parameters — avoids a stale selection
after a successful deletion while retaining URL state — cost if wrong: only fallback choice.

Task F10: Ruling: Watch items use kind+CIK profile routes, including company CIK; activity
uses unchanged shared feedColumns, with SEC source links — identity is CIK and the plan
requires feed-column reuse — cost if wrong: none, company route supports CIK.

Task F10: Ruling: named-list creation and deletion are available here; adding items follows
the existing profile Watch action, which targets the first list — F10 asks for list CRUD,
linked removable items and activity, while shared useWatch is outside this task's ownership —
cost if wrong: arbitrary target-list item adding needs a separate shared-hook change.

Task F12: Ruling: expose CommandDialog shouldFilter and disable local filtering for API results — server search ranks names, ticker aliases and subtitles, which local ID-based filtering would hide — cost if wrong: palette relies on the API ranking authority.
Task F12: Ruling: place dialog title/description inside dialog content and supply Command's label — existing wrapper did not provide an accessible input name — cost if wrong: shared wrapper accessibility only; keyboard and dialog tests cover it.
Task 12: complete (commits 69e27f5..af2497c, tests: npm test -- SearchPalette initial RED → 4 failures; npm test → 111 passed; npm run build && npm run lint → exit 0)
Task F13: Ruling: Browser plugin not available; use repository Playwright workflow — frontend-testing-debugging skill permits this fallback, and plan explicitly requires Playwright — cost if wrong: browser QA uses Chromium only.
Task 13: complete (commits af2497c..c011c78, tests: npx playwright test initial RED shortcut readiness failure → 12 passed after awaiting mounted route; npm test → 111 passed; npm run build && npm run lint → exit 0)
Task F13: Ruling: include DOM library types for browser-evaluated Playwright callbacks — e2e files share tsconfig.node with config files, and build caught missing document type — cost if wrong: config type context has additional browser globals.
Task F13: browser QA: desktop screener, compare light/dark and insider phone inspected; filter persists through reload; no route console errors or phone page overflow. Initial immediate checkbox.check raced React URL navigation; click plus retrying checked assertion verifies final state. Existing TanStack compiler and Vite bundle warnings remain.
