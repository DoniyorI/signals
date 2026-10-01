# Signals v2: insight-first dashboard, edge and backtesting, Congress trades, options ideas

- **Date:** 2026-10-01
- **Status:** draft for the user's review
- **Roles:** Claude is architect and reviewer. Executors (GPT or other coding agents) implement the plans.
- **Relationship to v1:** the v1 spec (`2026-09-27-sec-dashboard-design.md`) stays binding for everything it covers. This spec adds to it and changes only what it names explicitly.
- **Plans:** `docs/superpowers/plans/2026-10-01-signals-v2/` (start with `00-roadmap.md`).

## 1. Why v2

The user reviewed v1 against real data in a real browser on 2026-09-30:

- **Data was about 15% loaded.**
  - The 10-year backfill crashed on a database deadlock after loading insider filings from 2016 to mid-2017.
  - No prices were loaded, and fund holdings existed for only 3 funds.
  - As a result, both performance bases (filed and trade), all ratings and the screener were empty, and company pages showed $0 net buying.
  - The fix is in progress under v1 plan 08.
- **The UI is table-first.** It is long lists of filings and names with few charts and no "so what". It reads like an admin tool, not an insights dashboard. It was built against mock data and never reviewed with real data.
- **Most of the user's distinctive ideas aren't built.** Missing: Congress trades and committee power, options ideas, backtesting and edge, alerts, and senior officials.

User priorities (2026-09-30): first the redesign, then Congress trades, options ideas, and backtesting/edge. Alerts and OGE 278e officials are deferred.

## 2. Goals and non-goals

**Goals**

| Id | Goal |
|---|---|
| G0 | Complete, verified, self-healing data (finishing v1). |
| G1 | An insight-first, modern, intuitive UI: every page answers its question before it shows a table. |
| G2 | A point-in-time edge score, plus a backtest lab that shows whether copying signals actually works. |
| G3 | Congress trades (House and Senate periodic transaction reports) with committee context. |
| G4 | Options ideas for top signals, with transparent rules and stated risks. |

**Non-goals for v2:**
- real-time alert bots
- OGE 278e officials
- legislation/bill correlation
- order placement or broker integration
- multiple user accounts or a public launch
- any paid data service the user hasn't approved

## 3. Operating model

- **Claude (architect/reviewer)** writes and updates this spec and the plans, rules on conflicts, and reviews each finished phase. Executors implement tasks exactly as the plans state.
- **Ledgers are committed** in `docs/superpowers/ledgers/v2-<phase>.md`, one line per finished task and one per ruling. v1's ledgers were git-ignored and nearly lost.
- **Review gate per phase:**
  1. The executor writes `docs/superpowers/reports/v2-<phase>.md` (what was done, check results, rulings, open issues).
  2. Claude reviews the diff against this spec and the plan, and appends findings with severities to the same report.
  3. The executor fixes Critical and Important findings.
  4. The phase merges.
- **Branches:** one per phase (`v2/p<N>-<name>`), cut from `main` after v1 merges.

## 4. Product design (G1)

### 4.1 Principles

1. **Answer first.** Each page opens with the 3–5 facts that answer its question, then a chart, then the details.
2. **Every number explains itself.** Each shows its source link, its as-of time, and its basis ("from filing" or "from trade").
3. **Honest emptiness.** When data is missing, say why and when it will appear (for example, "Prices 37% loaded"). Never show a bare "—" or an unexplained "Not enough data yet".
4. **Signal over noise.** Open-market, discretionary trades are the headline. Routine filings are de-emphasized by default: grants, option exercises, tax withholding, and 10b5-1 plan sales.
5. **Fast.** Pages render from precomputed tables. Page API endpoints answer in p95 ≤ 300 ms, and first meaningful paint is ≤ 1.5 s on the local stack.
6. **Works on a phone.** Every page works at 390 px with no horizontal page scrolling.

### 4.2 Information architecture

- **Top navigation:** Today · Signals · Leaderboards · Backtest Lab (G2) · Options (G4) · Watchlist, plus ⌘K search.
- **Secondary (a menu and the footer):**
  - All filings (the v1 feed)
  - Screener
  - Compare
  - Data health
- **Entity pages:**
  - Stock (company)
  - Person: an insider or a member of Congress, sharing one template
  - Fund

### 4.3 Pages

**Today (home).** It answers "What did smart money do that matters?"
- **KPI strip:** today's and this week's insider buy $ and sell $, the number of cluster buys, new 13D activist stakes, and data freshness.
- **Top signals:** 6–9 cards. Each shows the ticker and company, the actor(s), the value, the score with its explanation chips, the return since filing against SPY, and a sparkline with the filing marked.
- **Cluster buys this week.**
- **Biggest buys by top-edge insiders** over the last 30 days.
- **Fund moves:** new and enlarged top positions from the latest 13F quarter.
- **Congress trades** (G3).
- **Market context:** SPY and QQQ, plus sector moves.

**Signals.** A ranked list of signals (cards on a phone, rows on desktop).
- Filters: actor type, role, value, sector, score, cluster, date range, and buy/sell.
- Every row explains its score with chips.

**Stock page.** It answers "Should I pay attention to this stock?"
- **Hero:** last price and change, market cap, and sector.
- **Insider sentiment:** net $ and buyer/seller counts over 3, 6 and 12 months, as a visual bar rather than bare numbers.
- **Main price chart:** defaults to 1 year (also 5 years and max), with markers for insider buys and sells, Congress trades (G3), 13F quarter changes and 13D/G stakes. Hovering a marker shows the trade.
- **"What happened after insiders bought here":** the number of past buys and their average excess return at 3, 6 and 12 months, filed basis.
- **Tabs:** Insiders (with edge), Institutions (13F holders and quarter-over-quarter change), Congress (G3), Options (G4), and a filings timeline.

**Person page.** It answers "Is this person worth following?"
- **Hero:** name, roles and companies, edge score with confidence, and their rank.
- **KPI row:** hit rate, average excess return at 6 months on both bases, number of decisions, average disclosure lag, and lag cost.
- **Copycat curve** against SPY, with a toggle between bases.
- **Best and worst calls.**
- **Trade list** with outcome chips (for example "+12% vs SPY at 6m").
- **Current holdings.**

**Fund page.**
- **Hero:** reported value, number of positions, turnover, and edge.
- **Sector allocation** bars.
- **Top holdings** with quarter-over-quarter change, plus new and exited positions.
- **Copycat curve** against SPY.

**Leaderboards.**
- Tabs: Insiders, Funds, Congress (G3).
- Ranked by point-in-time edge, with a minimum-data threshold and the confidence shown.
- Filters: role, sector, and period.

**Kept from v1:**
- **Screener:** simplified, with presets.
- **Compare.**
- **Watchlist:** now shows recent signals for the items you watch.

### 4.4 Signals (the core object)

A signal is one decision (episode) by one actor at one issuer, enriched for ranking.

**Fields:**
- the actor: kind, id, name, and role
- the issuer
- direction and value
- first and last trade dates
- the filing time
- entry prices on both bases
- the return since filing, and since filing against SPY
- a score from 0 to 100, with its components
- explanation chips

**Example chips:**
- "CEO"
- "Cluster of 3"
- "First buy in 2y"
- "Bought after −24% dip"
- "Edge: top 10%"
- "Late filing"
- "Committee overlap" (Congress)

**Scoring:**
- Score v0, the interim score built in P1, uses the v1 badges, the value, and the v1 rating.
- Score v1, built in P2, replaces it using point-in-time edge (§5).

### 4.5 Visual direction

P1's first task builds three static mockup directions, and the user picks one. This is a gate: no other P1 frontend work starts before the pick.

| Option | Direction | Description |
|---|---|---|
| A | Pro terminal | Dark, dense multi-panel grid, monospaced numerals, chart-heavy. |
| B | Modern fintech | Light-first with dark mode, roomy cards, big numbers, soft charts, tables below. **Recommended default.** |
| C | Signal stream | Narrative cards in a feed with inline mini-charts. |

The chosen direction becomes a design system:
- **Tokens:** color, type, spacing, radius and elevation, in both dark and light.
- **Colorblind-safe buy and sell colors:** blue and orange that also differ in lightness. Never green and red alone.
- **Tabular numerals** throughout.
- **A component kit:**
  - KPI stat
  - SignalCard
  - Sparkline
  - ActorChip
  - ScoreChip
  - ExplainChips
  - ChartPanel
  - SectionHeader
  - empty and loading states that state their reason

## 5. Edge score and backtesting (G2)

### 5.1 Point-in-time (PIT) edge

For an actor *a* of kind *k* (insider, fund, member) at time *t*:

**Inputs.** The actor's decisions whose filing acceptance is ≤ *t* AND whose outcome horizon ended ≤ *t*, so every outcome is fully known at *t*.
- The outcome is the 6-month excess return over SPY on the filed basis, from `decision_returns`.
- For funds, the outcome is quarterly excess return (v1 semantics).

**Shrinkage (empirical Bayes, normal–normal):**
- μ_t is the mean of all completed outcomes of kind *k* as of *t*.
- τ²_t is the between-actor variance, estimated by method of moments and floored at 1e-4.
- σ² is the pooled within-actor variance.
- Posterior mean: m = (n·x̄/σ² + μ_t/τ²_t) / (n/σ² + 1/τ²_t).
- Posterior standard deviation: s = (n/σ² + 1/τ²_t)^(-1/2).

**Edge score.** The edge score is m, the expected excess return of the actor's next signal, shown with s and n. Its percentile is taken among actors of the same kind with n ≥ 3 at *t*.

**Storage:**
- per decision, the value at that decision's filing time
- per actor, the value now

**No look-ahead.** A test must prove that adding an outcome after *t* never changes a PIT value at *t*.

### 5.2 Does edge predict? (validation)

1. Bucket decisions into deciles by their PIT edge percentile at filing.
2. Report the mean subsequent 6-month excess return per decile, the top-minus-bottom spread, and its t-statistic.
3. Break this down by year and overall, comparing in-sample (2016–2020) with out-of-sample (2021 onward).

The result is shown in the Backtest Lab. It's an empirical result: report it honestly, whatever it turns out to be.

### 5.3 Signal score v1

The score is a combination of these components:
- PIT edge percentile
- value relative to the actor's own history
- role: CEO/CFO > other officers > directors > 10% owners
- cluster count
- dip context (drawdown from the 52-week high)
- first buy in 2 years
- late filing (a penalty)
- 10b5-1 plan trades: excluded

Weights are fitted on 2016–2020 only and validated on 2021 onward, using the decile spread of the score. The weights and the validation numbers go in the ledger.

### 5.4 Backtest engine

**Strategy spec (JSON):**
- **Universe rules:**
  - actor kinds and roles
  - minimum PIT edge percentile and minimum score
  - minimum value and minimum cluster size
  - whether to exclude 10b5-1 trades
  - sectors and market-cap range
- **Entry:** filed basis, using the v1 entry rules.
- **Exit:** hold for 21, 63, 126 or 252 trading days, or exit when the actor sells. An optional stop-loss.
- **Sizing:** equal weight, maximum positions, maximum per issuer.
- **Costs:** basis points per side, default 10.
- **Period** and **benchmark:** SPY, optionally a sector ETF.

**Simulation:**
- Runs daily on the NYSE calendar with adjusted prices. Cash earns 0.
- A second signal for an issuer already held doesn't double the position.
- A delisted name exits at its last price and is flagged.
- Results are deterministic for a given spec and data version.

**Outputs:**
- equity curve against the benchmark, and drawdown
- CAGR, volatility, Sharpe, max drawdown and hit rate
- average excess per trade, turnover and exposure
- a yearly table and the trade list
- coverage (the % of signals that have prices)
- the data version

**Presets:**
- top-decile insider buys
- CEO/CFO buys over $250k
- cluster buys: ≥ 3 insiders within 10 trading days
- a first buy in 2 years after a 20% drop
- funds' new top-10 positions, filed basis
- top-decile Congress buys (after G3)

**Execution.** Runs are worker jobs. Results are stored, and the UI polls for completion.

## 6. Congress trades (G3)

### 6.1 Sources (default: official and free)

- **House:**
  - The Clerk's yearly financial-disclosure index: a ZIP holding an XML file with each filing's member name, state/district, filing type (P = periodic transaction report), filing date and DocID.
  - The PTR PDF for each DocID.
  - Electronic PTRs are text PDFs containing a transaction table.
  - Scanned PTRs need OCR. Store them and flag them `needs_review`; never drop them.
- **Senate:**
  - eFD search: accept the usage agreement, then use the report-search JSON.
  - Electronic PTRs are HTML tables.
  - Paper PTRs are images: store and flag them `needs_review`.
- **Members and committees:** the public-domain `unitedstates/congress-legislators` data, for BioGuide IDs, current and historical legislators, and current committees and memberships.
- **Optional paid source:** Quiver's Congress API, which includes BioGuideID and filing date. Use it only as a cross-check or backfill, and only if the user buys a key.
- **Verify first.** P3's first task verifies the exact URLs and records real samples as fixtures before any parser is written.

### 6.2 Data model

Members are keyed by BioGuide ID, never by name. Tables:
- `members`
- `committees`
- `committee_memberships`: current assignments; historical ones later
- `committee_sector_map`: a curated CSV
- `ptr_filings`: chamber plus document id; source URL; raw path; parse status; `needs_review`
- `ptr_transactions`:
  - owner: self, spouse, joint or dependent
  - asset name and the ticker as reported
  - asset type and transaction type
  - transaction date and notification date
  - the amount range as `amount_min` and `amount_max`
  - the mapped `issuer_cik`
  - comment

Every PDF and HTML page is raw-archived before parsing, as in v1 ground rule 1.

### 6.3 Analytics

- **Issuer mapping:** reported ticker → issuer through the dated ticker lookup; otherwise a name match. Unmapped rows are kept and shown.
- **Member decisions** follow the same episode rules as insiders.
  - Value is the midpoint of the reported range, with min and max kept.
  - The UI always shows the range and never a fake exact amount.
- **Bases:**
  - Filed: the next open after the filing date, since PTRs have no acceptance time.
  - Executed: the transaction date.
- **Badges:**
  - late filing: more than 45 days after the transaction
  - committee overlap: the issuer's sector falls under one of the member's committees
  - spouse trade
  - cluster: several members
- **Also:** PIT edge per member (§5.1), Congress leaderboards, and Congress signals.

### 6.4 Committee power vs. holdings

Per member, show:
- the share of their trading value in sectors their committees oversee
- the same share for their overall trading and for all members
- the list of overlapping trades

Assignments are labeled "current committees". Historical assignments are a later improvement.

### 6.5 Legal note

Federal law (the Ethics in Government Act) restricts using congressional financial disclosures for commercial purposes other than news media, for credit ratings, and for solicitation. Personal research use is fine. Before any public or paid launch, the user should get legal advice. Every Congress number links to its source document.

## 7. Options ideas (G4)

**Data (default free).** Alpaca options market data on the indicative feed:
- the contract list: expiration, strike, type and open interest
- snapshots: quote, last trade, implied volatility and greeks

OPRA real-time data is paid and stays off unless the user approves it. Indicative quotes aren't tradable quotes, and the UI says so.

**Universe.** Underlyings with a signal scoring ≥ 70 in the last 30 days, plus the watchlist.

**Snapshot cadence.** Daily after the close, plus on demand when a stock page opens (cached for 15 minutes). Stay within 200 requests/minute.

**Idea templates (bullish signals only in v2):**

1. **Long call:** 90–270 days to expiry, delta 0.55–0.70.
2. **Call debit spread:** one expiry; buy about 0.60 delta, sell about 0.30 delta.
3. **Cash-secured put:** 30–60 days to expiry, delta 0.20–0.30.

**Filters and context:**
- **Liquidity:** open interest ≥ 100 and bid–ask spread ≤ 10% of mid. Both are configurable.
- **IV context:**
  - Implied volatility against 30-day realized volatility, shown as "rich" or "cheap".
  - IV rank only once a year of our own snapshots exists.

**Each idea shows:**
- the thesis (the signal behind it)
- the structure
- cost or credit
- max loss and max gain
- breakeven
- delta-based probability of finishing in the money
- a payoff chart at expiry
- liquidity
- the data time
- "Not investment advice"

**Tracking.** Ideas are marked to market daily after they're generated, so their real outcomes accumulate. There is no historical options backtest from before Alpaca's options history (2024).

**No order placement.**

## 8. Data completeness and self-healing (G0)

- **Finish v1 plan 08:** backfill, spot check, latency, browser checks on real data, security sweep, review, and the merge to `main`.
- **Completeness report**, covering:
  - per quarter, SEC full-index accession counts against stored filings, by form family (3/4/5, 144, 13D/G, 13F)
  - insider transactions per year
  - price coverage
  - decisions with returns on both bases
  - coverage for each tracked fund and quarter
- **Completeness target:** ≥ 99.5% of index accessions per quarter, from 2016 on.
- **Gap handling:** gaps automatically queue a gap fill.
- **Where it shows:** on Data health, and summarized in the header's freshness indicator.
- **Catch-up for missed scheduled jobs:** runs at startup and every 15 minutes (in progress under plan 08).
- **"Why empty" states:** every empty state uses the completeness report to say why it's empty.

## 9. Global constraints (all phases)

**Carried over from v1.** All of v1's hard rules (CLAUDE.md) still apply:
- Key everything by CIK, accession number or CUSIP (BioGuide ID for members), never by ticker.
- Never delete raw data.
- Every SEC request goes through `SecClient`.
- Measure follower returns on the filed basis.
- Keep the two calendars.
- No silent failures.
- Secrets live only in `.env`.

**New in v2:**
- **Point-in-time.** Anything used to rank or select a past signal uses only information that was available at that signal's filing time.
- **Every number shows its source link and as-of time.**
- **Footer.** It changes in P3 to "Data from SEC EDGAR, the House Clerk and the U.S. Senate. Not investment advice." Until then it keeps v1's exact text.
- **API changes.** Regenerate `frontend/src/api/openapi.json` and `schema.d.ts`, and update the MSW mocks in the same task. Never hand-edit the generated types.
- **Schema changes** go in Alembic revisions named `v2_<phase>_<desc>.py`, each reversible.
- **Tests.**
  - TDD against real Postgres.
  - Recorded real fixtures for every external source; no network in tests.
  - Playwright on both mock data and real data.
- **Performance budgets** as in §4.1.
- **No paid services and no new external accounts** without the user's approval.

## 10. Decisions (defaults chosen; the user can override)

| Decision | Default | Alternative |
|---|---|---|
| Visual direction | B, Modern fintech (confirmed at the P1 mockup gate) | A or C |
| Congress data source | Official House and Senate sources (free) | Quiver API (paid) |
| Options data | Alpaca indicative feed (free) | OPRA through Alpaca's paid plan |
| Committee history | Current assignments only | Historical assignments (later) |
| Phase order | P0 → P1 → (P2 and P3 in parallel) → P4 | — |
