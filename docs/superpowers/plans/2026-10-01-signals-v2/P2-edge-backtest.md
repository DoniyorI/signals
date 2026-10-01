# P2: Point-in-time edge, signal score v1, Backtest Lab

- **Goal:** answer "does following these people actually work?" honestly. That means:
  - a point-in-time (PIT) edge score per actor
  - a validation of whether that score predicts anything
  - a signal score built on it
  - a Backtest Lab that simulates copying signals against SPY
- **Branch:** `v2/p2-edge-backtest` from `main`, after P1.1–P1.4 have merged. **Ledger:** `docs/superpowers/ledgers/v2-p2.md`.
- **Spec:** v2 spec §5. Analytics inputs come from v1: `decisions`, `decision_returns` (filed and executed, horizons of 21, 63, 126 and 252 trading days), `prices_daily` via `analytics/series.py`, and `analytics/entries.py` for entry rules.

## Review Focus

1. **Look-ahead.**
   - A PIT value must use only outcomes whose 126-trading-day horizon ended at or before the query time.
   - The v1 rating is NOT point-in-time, so it must never feed a backtest.
2. **Survivorship.**
   - Delisted issuers must stay in the backtest, exiting at their last price, and be flagged.
   - Report coverage.
   - Never silently drop a signal that has no prices.
3. **Train/test leakage.** Score v1 is fitted on decisions filed before 2021-01-01 only.
4. **Double counting.**
   - A second signal for an issuer already held doesn't add a position.
   - Clusters count distinct owner groups, not rows.
5. **O(N²) PIT computation.** About 1M decisions must finish in minutes. Use the sweep described in P2.1.
6. **Nondeterminism.** The same spec and data version must give identical results.

---

### Task P2.1: PIT edge

**Files:**
- `backend/migrations/versions/v2_p2_edge.py`
- `backend/src/signals/analytics/edge.py` (new)
- tests: `backend/tests/unit/test_edge_math.py`, `backend/tests/integration/test_edge_pit.py`

**Tables:**
- **`decision_edge`:**
  - `decision_id` PK
  - `actor_kind`, `actor_id`
  - `as_of`: the decision's `filed_at`
  - `n_completed`, `x_bar`
  - `post_mean`, `post_sd`, `percentile`
  - `mu`, `tau2`, `sigma2`
- **`actor_edge_current`:**
  - `actor_kind`, `actor_id`
  - `n`, `post_mean`, `post_sd`, `percentile`
  - `as_of`
  - PK: (`actor_kind`, `actor_id`)

**Interfaces:**
- `shrink(n, x_bar, mu, tau2, sigma2) -> tuple[float, float]`: the posterior mean and posterior sd, per spec §5.1.
- `compute_edge(session, *, actor_kind: str, as_of: date) -> EdgeRunResult`: fills both tables for that kind.

**Outcomes:**
- **Insiders:** a decision's outcome is its filed-basis 126-day excess return over SPY. It becomes known at the exit date of that horizon.
- **Funds:** each 13F period's quarterly excess, known at the next period's start.

**Algorithm (required, O(N log N)): one sweep over time-ordered events.**
1. Build two kinds of events:
   - completion events: (outcome known date, actor, outcome)
   - query events: (decision `filed_at`, decision)
2. Sort them by time, with completions before queries at the same instant.
3. Keep running state:
   - per-actor n, sum and sum of squares
   - global aggregates that are updated incrementally whenever an actor's stats change: total n, the sums used for the pooled σ², and the sums of actor means and squared means used for τ² by method of moments, with τ² floored at 1e-4
4. At each query event, compute the shrunk value for that decision's actor. Its percentile is taken among actors with n ≥ 3 at that instant: keep a sorted structure of their posterior means, or recompute in batches per day. Record which you used as a ruling.

**Tests (write first):**
- `test_shrink_matches_hand_computed`: three cases, including n = 0, which returns mu and sqrt(tau2).
- `test_no_lookahead_future_outcome_does_not_change_past_value`: add an outcome completing after t; the PIT values at t are unchanged.
- `test_outcome_counts_only_after_horizon_end`: a decision filed 3 months before t is not in n at t.
- `test_percentile_only_among_n_ge_3`
- `test_sweep_equals_naive_reference`: a seeded random synthetic world of 300 decisions; the sweep matches a naive O(N²) reference within 1e-9.
- `test_current_edge_equals_pit_at_now`

**Commit:** `feat(analytics): point-in-time edge with empirical-Bayes shrinkage`

### Task P2.2: "Does edge predict?" validation

**Files:**
- `backend/src/signals/analytics/edge_validation.py`
- the `edge_validation` job
- results stored in `app_state["edge_validation:<kind>"]`
- tests

**Interface:** `edge_validation(session, *, actor_kind, split_date=date(2021,1,1)) -> EdgeValidation`, containing:
- deciles by PIT percentile at filing
- per decile: n, mean, and standard error of the 6-month excess
- the top-minus-bottom spread with its t-statistic
- everything per year, and for in-sample versus out-of-sample

**Tests (write first):**
- `test_planted_edge_gives_positive_out_of_sample_spread`: synthetic actors with a true mean, plus noise.
- `test_random_world_spread_within_two_se_of_zero`
- `test_deciles_use_pit_percentile_not_current`

**Commit:** `feat(analytics): edge validation by decile`

### Task P2.3: Signal score v1

**Files:**
- `backend/src/signals/analytics/score_v1.py`
- `backend/src/signals/analytics/signals.py` (switch to v1, keep v0 as the fallback)
- tests

**Features** (standardized on the training set):
- PIT edge percentile, where n < 3 maps to 0.5
- log of value relative to the actor's own median
- role rank
- cluster count
- 52-week drawdown at filing
- first buy in 2 years
- late filing

**Model:**
1. Fit a ridge regression (closed form with numpy, λ = 1.0) of the 126-day filed-basis excess return on decisions filed before 2021-01-01.
2. Score = the percentile of the predicted value within the training predictions, scaled to 0–100.

**Storage and output:**
- Store the weights and the training summary in `app_state["score_v1_model"]`, with a version.
- Chips gain "Edge: top X%".
- Planned decisions still score 0.

**Tests (write first):**
- `test_training_uses_only_pre_2021_decisions`
- `test_score_deterministic_for_same_data`
- `test_score_monotone_in_prediction`
- `test_falls_back_to_v0_without_model`
- `test_out_of_sample_decile_spread_reported`, with its value recorded in the ledger.

**Commit:** `feat(analytics): signal score v1 with out-of-sample validation`

### Task P2.4: Backtest engine (pure)

**Files:**
- `backend/src/signals/analytics/backtest/{spec.py,engine.py,metrics.py}`
- tests: `backend/tests/unit/test_backtest_engine.py`

**Interfaces:**
- `StrategySpec`, a pydantic model:
  - **universe:** actor kinds, roles, `min_edge_pct`, `min_score`, `min_value`, `cluster_min`, `exclude_planned` (default true), sectors, and market-cap range
  - **entry:** `filed`, the only option in v2
  - **exit:** hold in trading days (21, 63, 126 or 252), `exit_on_actor_sell` (bool), `stop_loss_pct` (optional)
  - **sizing:** `max_positions` (default 20), `max_per_issuer` (1)
  - **costs:** `cost_bps` (10)
  - **period:** start and end
  - **benchmark:** SPY
- `run_backtest(spec, signals: DataFrame, prices: PricePanel, calendar) -> BacktestResult`
  - `BacktestResult` contains: `equity` (date, nav, bench), `trades`, `metrics` and `coverage`

**Rules:**
- **Entries:**
  - Take signals in filing-time order.
  - Skip a signal when its issuer is already held, or when `max_positions` is reached; record it as `skipped_reason`.
  - Use equal weight of current NAV: each new position gets NAV / `max_positions`, taken from cash.
- **Exits:** at the earliest of the horizon close, the actor's sell (if enabled), or the stop.
- **Delisting:** a delisted name exits at its last price with `exit_reason="delisted"`.
- **Costs:** charged on both sides.
- **Cash** earns 0.

**Metrics:**
- CAGR
- annualized volatility (√252) and Sharpe (risk-free = 0)
- max drawdown
- hit rate and average excess per trade against the benchmark
- turnover and average exposure
- yearly returns

**Tests (write first)**, on synthetic prices whose outcomes are known in advance:
- `test_single_trade_return_and_costs`
- `test_equal_weight_and_max_positions_skip`
- `test_same_issuer_not_doubled`
- `test_exit_on_actor_sell`
- `test_delisted_exit_flagged`
- `test_metrics_formulas`: CAGR, volatility, Sharpe and drawdown each against hand-computed values
- `test_deterministic`

**Commit:** `feat(analytics): backtest engine`

### Task P2.5: Presets, persistence, jobs

**Files:**
- `backend/migrations/versions/v2_p2_backtests.py`
- `backend/src/signals/analytics/backtest/{presets.py,store.py,jobs.py}`
- tests

**Tables:**
- **`backtest_runs`:**
  - `id`, `spec` (jsonb), `spec_hash`, `data_version` (the `analytics_version` stamp)
  - `status`, `requested_at`, `started_at`, `finished_at`, `error`
  - `metrics` (jsonb), `coverage` (jsonb)
- **`backtest_equity`:** `run_id`, `date`, `nav`, `bench`
- **`backtest_trades`:**
  - `run_id`, `decision_id`, `issuer_cik`
  - `entry_date`, `entry_price`, `exit_date`, `exit_price`
  - `ret`, `excess`, `exit_reason`

**Behavior:**
- **Job `backtest_run`:** takes `run_id` and loads the signals and prices set-based, in one query each.
- **Reuse:** the same `spec_hash` and `data_version` reuse a finished run.
- **Presets:** per spec §5.4. The Congress preset is added in P3.

**Tests (write first):**
- `test_job_persists_equity_trades_metrics`
- `test_same_spec_and_version_reuses_run`
- `test_new_analytics_version_reruns`
- `test_presets_valid_specs`
- `test_failed_run_records_error` (no silent failures)

**Commit:** `feat(analytics): backtest presets, storage and jobs`

### Task P2.6: Backtest and research API

**Endpoints:**
- `POST /api/backtests` takes a `StrategySpec` and returns `{id, status}`.
- `GET /api/backtests/{id}` returns the run, equity, metrics, coverage and paged trades.
- `GET /api/backtests` returns recent runs.
- `GET /api/backtests/presets`
- `GET /api/research/edge-validation?kind=` returns the P2.2 report.

**Also:** regenerate the OpenAPI document and the types, and update the MSW mocks.

**Tests:**
- `test_post_validates_spec`
- `test_get_running_then_done`
- `test_trades_paginated`
- `test_edge_validation_endpoint`

**Commit:** `feat(api): backtests and edge validation`

### Task P2.7: Backtest Lab UI

**Route:** `/lab`.

**Content:**
- **Preset gallery.**
- **Builder form** with validation. Every field explains itself in one line.
- **Results:**
  - equity against SPY
  - drawdown
  - a metrics grid
  - yearly returns
  - the trades table, with links to signals
  - a coverage note: "N signals had no prices: listed"
- **Compare two runs** side by side.
- **"Does edge predict?" panel:** decile bars, with in-sample and out-of-sample toggles and the result stated plainly. An example: "Top-decile insiders beat bottom-decile by 3.1%/6m out-of-sample (t = 2.4)".

**Tests:**
- `preset runs and shows results`
- `form rejects invalid spec with message`
- `coverage note lists missing-price signals`
- `edge panel shows out-of-sample spread`

**Commit:** `feat(web): Backtest Lab`

### Task P2.8: Switch rankings to PIT edge

**Changes:**
- **Leaderboards** rank by `actor_edge_current`.
- **Person pages** show an edge-history chart (the PIT value at each decision) plus n and confidence.
- **Signals** use score v1.
- **Today's "top-edge insiders"** section uses PIT edge.
- **The v1 rating** stays visible only as "historical rating", or is removed. Record that as a ruling.

**Tests:**
- `leaderboard order matches actor_edge_current`
- `person edge history renders PIT points`
- `today uses score v1`

**Commit:** `feat: rank by point-in-time edge`

**Phase end:** write `docs/superpowers/reports/v2-p2.md`, including the validation numbers stated plainly, and request Claude's review.
