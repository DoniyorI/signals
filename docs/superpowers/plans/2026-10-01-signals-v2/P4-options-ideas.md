# P4: Options ideas

- **Goal:** for the strongest bullish signals, show options chains and a few transparent, rule-based ways to express the view. Each one comes with its exact risks, liquidity and data time. Track every idea's real outcome from the day it's generated.
- **Not in scope:** order placement.
- **Branch:** `v2/p4-options` from `main`, after P2 (it needs score v1). **Ledger:** `docs/superpowers/ledgers/v2-p4.md`.
- **Spec:** v2 spec §7.
- **Data:** Alpaca options market data on the free indicative feed, using the user's existing key in `.env` (never printed). The paid OPRA feed only with the user's approval.

## Review Focus

1. **Indicative quotes presented as tradable.** Every price says "indicative" and shows its timestamp.
2. **Wrong payoff math.** Max loss, max gain and breakeven for each template need tests with hand-computed values, including fees set to 0.
3. **Illiquid contracts suggested.** Enforce open interest and spread filters, and show why a stock has no idea, for example "no contract met liquidity".
4. **Rate-limit starvation of the stock-price job.** One shared Alpaca limiter (200 requests/minute), with prices given priority.
5. **Look-ahead in the track record.** An idea's entry is the mid price at creation time and is never revised.

---

### Task P4.1: Provider and fixtures

**Files:**
- `backend/src/signals/options/alpaca_options.py`
- `backend/tests/fixtures/options/…`
- the fixture manifest
- tests

**Verify, then record** fixtures with the user's key (trimmed and anonymized; never commit the key):
- The **contract list** from the Trading API (`/v2/options/contracts`, filtered by underlying and expiration range): OCC symbol, expiration, strike, type, open interest and its date.
- The **chain snapshots** from the Market Data API (`/v1beta1/options/snapshots/{underlying}` with `feed=indicative`, paginated): latest quote, latest trade, implied volatility and greeks.

**Also:**
- Confirm the free plan returns the indicative feed. Record the real field names; if they differ from the above, the real ones win (ruling).
- Share the rate limiter with `prices/alpaca.py`, which has priority.

**Tests (write first):**
- `test_contracts_paginate_and_parse`
- `test_snapshots_parse_greeks_and_iv`
- `test_shared_limiter_prioritizes_prices`
- `test_missing_greeks_tolerated`

**Commit:** `feat(options): Alpaca options provider`

### Task P4.2: Chain storage and the daily snapshot job

**Files:**
- `backend/migrations/versions/v2_p4_options.py`
- `backend/src/signals/options/store.py` and `jobs.py`
- tests

**Tables:**
- **`option_contracts`:**
  - `occ_symbol` PK
  - underlying, expiration, strike, type
  - open interest and its date
- **`option_snapshots`:**
  - `occ_symbol`, `ts`
  - bid, ask, last
  - IV, delta, gamma, theta, vega
  - `feed`
  - Snapshots are kept to build IV history.

**Jobs:**
- **`options_daily`:** Mon–Fri at 18:45 ET, after `prices_daily`, and included in the catch-up order.
  - Universe: underlyings with a signal scoring ≥ 70 in the last 30 days, plus the watchlist.
  - Expirations: 20–300 days out.
- **On-demand refresh** for one underlying, with a 15-minute cache.

**Tests (write first):**
- `test_daily_snapshots_universe_only`
- `test_cache_prevents_refetch_within_15_min`
- `test_snapshot_history_kept`

**Commit:** `feat(options): chain storage and daily snapshots`

### Task P4.3: Idea engine (pure functions)

**Files:**
- `backend/src/signals/options/ideas.py`
- tests: `backend/tests/unit/test_option_ideas.py`

**Templates.** Each works from a chain and a bullish signal.
1. **Long call:**
   - 90–270 days to expiry, delta 0.55–0.70
   - Choose the expiry nearest 180 days and the strike nearest delta 0.62.
2. **Call debit spread:**
   - Same expiry rules.
   - Buy the call nearest delta 0.60 and sell the one nearest delta 0.30.
3. **Cash-secured put:**
   - 30–60 days to expiry, delta 0.20–0.30
   - Choose the strike nearest delta 0.25.

**Filters,** applied to every leg:
- open interest ≥ 100
- (ask − bid) / mid ≤ 10%
- bid > 0

**Math,** per contract × 100:
- **Long call:** cost = mid; max loss = cost; max gain = unbounded; breakeven = strike + mid.
- **Call debit spread:** cost = long mid − short mid; max loss = cost; max gain = width − cost; breakeven = long strike + cost.
- **Cash-secured put:** credit = mid; capital = strike × 100; max loss = (strike − mid) × 100; breakeven = strike − mid; annualized yield = credit / (strike − credit) × 365 / days to expiry.
- **Probability ITM:** approximated by |delta|, labeled "approx".

**IV context:** IV against 30-day realized volatility from `prices_daily`.
- "rich" when IV / RV > 1.25
- "cheap" when IV / RV < 0.8

**Ranking:** signal score × liquidity score, where liquidity score = min(1, OI / 1000) × (1 − spread %).

**Tests (write first):**
- `test_long_call_selection_and_payoff`
- `test_debit_spread_payoff_and_breakeven`
- `test_csp_capital_breakeven_and_yield`
- `test_liquidity_filters_exclude_wide_or_thin`
- `test_no_idea_reason_reported`
- `test_iv_rich_cheap_chip`

**Commit:** `feat(options): rule-based idea engine`

### Task P4.4: Idea tracking

**Files:**
- the migration (`option_ideas` and `option_idea_marks`)
- `backend/src/signals/options/tracking.py`
- tests

**Behavior:**
- **On generation:** store the idea with its signal decision, template, legs, entry mid at creation, and the computed risks. The entry is never revised.
- **Every day:** mark each open idea at mid from that day's snapshot until expiry.
- **At expiry:** compute the outcome from the underlying's close.

**Track record:**
- the number of ideas
- the share profitable at expiry
- the average return on risk, per template

**Tests (write first):**
- `test_entry_frozen_at_creation`
- `test_daily_marks_until_expiry`
- `test_expiry_outcome_from_underlying_close`
- `test_track_record_aggregates`

**Commit:** `feat(options): idea tracking and track record`

### Task P4.5: Options API

**Endpoints:**
- `GET /api/options/{symbol}/chain?expiration=`: strikes near the money, with quotes, IV and greeks, plus `as_of` and `feed`
- `GET /api/options/ideas?min_score=&template=`
- `GET /api/options/ideas/{id}`
- `GET /api/options/track-record`
- Regenerate the OpenAPI document and the types, and update the mocks.

**Tests:**
- `test_chain_marks_indicative_and_as_of`
- `test_ideas_filtered_and_ranked`
- `test_track_record_endpoint`

**Commit:** `feat(api): options chains and ideas`

### Task P4.6: Options UI

**Options page** (`/options`), a list of ideas. Each card shows:
- the thesis: the signal, with its chips and a link
- the structure, as legs
- cost or credit
- max loss and max gain
- breakeven
- approximate probability ITM
- a payoff chart at expiry
- liquidity
- the IV chip
- "indicative · <time>"
- the disclaimers: "Ideas are generated by fixed rules from public filings. Not investment advice. Options can lose 100% of the premium."

**Stock page Options tab:**
- the chain near the money
- the ideas for this stock
- a "why none" reason when there are no ideas

**Track-record panel:** shown on the Options page.

**Tests:**
- `card shows risks and disclaimer`
- `payoff chart matches max loss/gain`
- `no-idea reason shown`
- `track record renders`

**Commit:** `feat(web): Options ideas`

**Phase end:** write the report, including the number of ideas generated on real data and the reasons stocks had no idea, then request Claude's review.
