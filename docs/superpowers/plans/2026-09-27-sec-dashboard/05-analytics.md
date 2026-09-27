# Workstream D: Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn canonical trades, holdings and prices into the track-record numbers in spec section 9:
- decisions (episodes)
- filed and executed entry prices
- per-decision returns at 1/3/6/12 months against SPY, QQQ and the sector
- insider and fund copycat portfolios with YTD/1/3/5-year windows
- risk, reliability ratings, allocation and concentration
- badges and positions

It also implements the API's curve service.

**Architecture:**
- Pure functions over pandas objects hold all the math, so they're unit-testable with hand-computed series.
- Thin database functions load inputs and write derived tables.
- `run.py` orchestrates full and incremental runs, replacing each table group inside one transaction.

**Tech Stack:** Python 3.13, pandas 3, numpy 2.5, SQLAlchemy 2.1, the foundation calendars.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, section 9 (all of it) and section 8 (derived tables).

## Global Constraints

Everything in `00-overview.md` › Global Constraints. On top of that:
- Work on branch `ws/d-analytics`. Your stubs are `analytics/curves.py` and `analytics/jobs.py`. Only create or modify the files listed here, plus their tests.
- Prices are always compared on the adjusted scale: `adjusted = raw × adj_factor(date)`.
- Horizons are 21/63/126/252 trading days. Windows are 252/756/1260 trading days plus YTD.
- Shrinkage `k` is 5 for insiders and 4 for funds.
- Confidence for insiders: Low under 5, Medium 5–15, High over 15. For funds: Low under 4, Medium 4–12, High over 12.
- Risk thresholds: Low under 0.20, Medium 0.20–0.40, High over 0.40.
- The badge constants come from spec 9.8.
- Before starting, run `docker compose up -d db`.

## Review Focus

- Overview item 1 (ticker changes): D1 `test_series_stitches_ticker_change`.
- Item 2 (entry timing): D3 `test_filed_entry_*`.
- Item 3 (empty profiles): D8 `test_rating_none_without_complete_decisions`.
- Item 4 (splits): D3 `test_executed_entry_applies_split_factor` and D4 `test_returns_across_split`.

## Interfaces consumed

- **Foundation:** `calendars` (`ET`, `trading_days`, `add_trading_days`, `next_trading_day`, `prev_trading_day`, `is_trading_day`, `session_open_close`, `sec_business_days_between`), `ticker_intervals`, `get_bars`, `SECTOR_ETF`, `BENCHMARK_SYMBOLS`, the enums in `types`, `analytics.types.Curve` and `WindowResult`, the models, `register_job`, `JobContext`, the fixtures and the factories.
- **Workstream B:** `signals.ingest.fund_changes.compute_fund_changes`. Call it through a module-level wrapper `_fund_changes(session)` that imports it inside the function, and monkeypatch the wrapper in tests.

## Interfaces produced

- `signals.analytics.series`: `IssuerSeries`, `load_issuer_series`, `load_symbol_series`, `BenchPanel`, `load_bench`
- `signals.analytics.decisions`: `group_episodes` and `build_decisions`
- `signals.analytics.entries`: `Entry`, `filed_entry` and `executed_entry`
- `signals.analytics.returns`: `HorizonResult`, `horizon_returns`, `lag_cost` and `compute_decision_returns`
- `signals.analytics.copycat`: `Lot`, `SaleEvent` and `copycat_nav`
- `signals.analytics.windows`: `window_stats` and `risk_label`
- `signals.analytics.funds`: `FundPeriodHoldings`, `load_fund_periods`, `fund_copycat_nav`, `fund_quarterly_excess`
- `signals.analytics.stats`: `ProfileSummary`, `summarize`, `shrunk_mean`, `percentile_ratings`, `confidence_insider`, `confidence_fund`, `compute_profile_stats` and `compute_fund_stats`
- `signals.analytics.allocation`: `insider_high_conviction`. The shared portfolio helpers (`effective_n`, `top5_weight`, `allocation_slices`, `fund_high_conviction`) live in the foundation's `signals.domain.portfolio`. Import them from there.
- `signals.analytics.badges`: `compute_badges`
- `signals.analytics.positions`: `build_positions`
- `signals.analytics.run`: `RunResult`, `run_full` and `run_incremental`
- `signals.analytics.curves`: `insider_curve` and `fund_curve`, implementing the foundation stubs. `fund_curve` raises `LookupError` for untracked funds.
- Jobs: `analytics_full` and `analytics_incremental` (params `issuer_ciks` and `owner_ciks`)

---

### Task D1: Price series with ticker stitching

**Files:**
- Create: `backend/src/signals/analytics/series.py`
- Test: `backend/tests/integration/test_series.py`

**Interfaces:**

```python
@dataclass
class IssuerSeries:
    issuer_cik: int | None
    frame: pd.DataFrame   # index: date objects (trading days, ascending);
                          # columns: symbol, open, close, adj_factor, open_adj, close_adj
    def has(self, d: date) -> bool
    def open_adj(self, d: date) -> float | None
    def close_adj(self, d: date) -> float | None
    def factor_on_or_before(self, d: date) -> float | None
    def first_date(self) -> date | None
    def last_date(self) -> date | None

def load_issuer_series(session, issuer_cik: int, start: date, end: date) -> IssuerSeries
def load_symbol_series(session, symbol: str, start: date, end: date) -> IssuerSeries
@dataclass
class BenchPanel:
    series: dict[str, IssuerSeries]
    def get(self, symbol: str | None) -> IssuerSeries | None
def load_bench(session, start: date, end: date) -> BenchPanel     # BENCHMARK_SYMBOLS
```

**Stitching rules for `load_issuer_series`:**
- For each trading date, use the bar of the symbol whose ticker interval contains that date.
- If that symbol has no bar that day, use the current symbol's bar when one exists. (Some providers map history onto the new symbol.)
- Then, walking segment boundaries from newest to oldest, multiply each older segment's `adj_factor` by `factor_new(first day of newer segment) / factor_old(last day of older segment)`. That makes `adj_factor` continuous, since a rename is not a corporate action.
- `adj_factor = adj_close / close`, `open_adj = open × adj_factor` and `close_adj = close × adj_factor`.

- [ ] **Step 1: Write the failing tests:**

```python
def _globex(session):
    make_issuer(session, cik=1000002, name="Globex Inc", ticker="GBX", ticker_from=date(2016, 1, 4))
    record_ticker_evidence(session, 1000002, "GBX", date(2016, 1, 4), "t")
    record_ticker_evidence(session, 1000002, "GLBX", date(2022, 6, 10), "t")
    rebuild_tickers(session, [1000002])

def test_series_stitches_ticker_change(session):
    _globex(session)
    make_prices(session, "GBX", date(2022, 6, 6), [10.0] * 4, adj_factors=[0.5] * 4)     # Jun 6-9
    make_prices(session, "GLBX", date(2022, 6, 10), [10.1, 10.2], adj_factors=[1.0, 1.0])  # Jun 10, 13
    s = load_issuer_series(session, 1000002, date(2022, 6, 1), date(2022, 6, 30))
    assert list(s.frame["symbol"]) == ["GBX"] * 4 + ["GLBX"] * 2
    assert s.close_adj(date(2022, 6, 9)) == pytest.approx(10.0)
    assert s.close_adj(date(2022, 6, 10)) / s.close_adj(date(2022, 6, 9)) - 1 == pytest.approx(0.01)

def test_series_prefers_current_symbol_history(session):
    _globex(session)
    make_prices(session, "GLBX", date(2022, 6, 6), [10.0, 10.0, 10.0, 10.0, 10.1, 10.2])
    s = load_issuer_series(session, 1000002, date(2022, 6, 1), date(2022, 6, 30))
    assert set(s.frame["symbol"]) == {"GLBX"} and len(s.frame) == 6

def test_factor_on_or_before_weekend(session):
    make_issuer(session); make_prices(session, "ACME", date(2024, 5, 31), [100.0], adj_factors=[0.5])
    s = load_issuer_series(session, 1000001, date(2024, 5, 1), date(2024, 6, 30))
    assert s.factor_on_or_before(date(2024, 6, 1)) == 0.5 and s.has(date(2024, 6, 1)) is False
```

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_series.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): adjusted price series with ticker stitching`.

---

### Task D2: Decisions (episodes)

**Files:**
- Create: `backend/src/signals/analytics/decisions.py`
- Test: `backend/tests/unit/test_episodes.py`, `backend/tests/integration/test_build_decisions.py`

**Interfaces:**
- `group_episodes(trades: pd.DataFrame) -> pd.DataFrame`
  - **Input columns:** `tx_id, accession_no, owner_group, owner_ciks (list[int]), issuer_cik, code ('P'|'S'), is_planned (bool), plan_10b5_1, transaction_date, shares, price, shares_owned_after, row_order (int), accepted_at, filed_date`.
  - **Output:** one row per decision with columns `owner_group, owner_ciks, issuer_cik, direction ('buy'|'sell'), is_planned, plan_10b5_1, first_trade_date, last_trade_date, shares, value_usd, vwap, stake_change_pct, is_new_position, sell_fraction, first_accession, accessions (list), accepted_at, filed_date, lag_days`.
  - **Grouping:** by `(owner_group, issuer_cik, direction, is_planned)`, ordered by `(transaction_date, row_order)`. A trade starts a new episode when `trading_days_between(prev_trade_date, trade_date) > 10`.
  - `vwap` = Σ(shares·price) / Σ(shares) over rows on `first_trade_date` with `price > 0`. None if there are no such rows.
  - **Buys:** `shares_before = shares_owned_after(first row of the first day) − shares(that row)`. `stake_change_pct = total shares / shares_before` when `shares_before > 0`. Otherwise `is_new_position = True` and `stake_change_pct = None`.
  - **Sells:** `sell_fraction = total shares sold / (total shares sold + shares_owned_after of the last row)`.
  - `accepted_at` and `filed_date` come from the earliest-accepted filing in the episode, and so does `first_accession`.
  - `lag_days = sec_business_days_between(first_trade_date, accepted_at.astimezone(ET).date())`.
- `build_decisions(session, *, issuer_ciks: Collection[int] | None = None) -> int`:
  - Loads non-superseded, non-derivative P and S rows (for the given issuers, or all).
  - `is_planned = plan_10b5_1 != 'none'`.
  - `value_usd` = Σ shares·price (rows without a price excluded).
  - Replaces `decisions` and `decision_owners` for those issuers and returns the count.

- [ ] **Step 1: Write the failing tests:**

```python
def tx(d, code="P", shares=100.0, price=10.0, after=1100.0, group="2000001", planned=False, acc="A1", order=1):
    return dict(tx_id=order, accession_no=acc, owner_group=group, owner_ciks=[int(g) for g in group.split("|")],
                issuer_cik=1000001, code=code, is_planned=planned, plan_10b5_1="flag" if planned else "none",
                transaction_date=d, shares=shares, price=price, shares_owned_after=after, row_order=order,
                accepted_at=datetime.combine(d, time(17, 0), ET) + timedelta(days=2), filed_date=d + timedelta(days=2))

def test_within_10_trading_days_is_one_episode():
    df = group_episodes(pd.DataFrame([tx(date(2024,1,2)), tx(date(2024,1,10), order=2), tx(date(2024,1,17), order=3)]))
    assert len(df) == 1 and df.iloc[0].first_trade_date == date(2024,1,2) and df.iloc[0].last_trade_date == date(2024,1,17)

def test_gap_over_10_trading_days_splits():
    assert len(group_episodes(pd.DataFrame([tx(date(2024,1,2)), tx(date(2024,1,18), order=2)]))) == 2

def test_planned_and_discretionary_never_merge():
    assert len(group_episodes(pd.DataFrame([tx(date(2024,1,2)), tx(date(2024,1,3), planned=True, order=2)]))) == 2

def test_vwap_first_day_only():
    rows = [tx(date(2024,1,2), shares=100, price=10), tx(date(2024,1,2), shares=300, price=12, order=2),
            tx(date(2024,1,3), shares=50, price=20, order=3)]
    assert group_episodes(pd.DataFrame(rows)).iloc[0].vwap == pytest.approx(11.5)

def test_stake_change_and_new_position():
    a = group_episodes(pd.DataFrame([tx(date(2024,1,2), shares=200, after=1200)])).iloc[0]
    b = group_episodes(pd.DataFrame([tx(date(2024,1,2), shares=500, after=500)])).iloc[0]
    assert a.stake_change_pct == pytest.approx(0.2) and not a.is_new_position
    assert b.is_new_position and b.stake_change_pct is None

def test_sell_fraction_multi_row():
    rows = [tx(date(2024,1,2), code="S", shares=100, after=900), tx(date(2024,1,3), code="S", shares=150, after=750, order=2)]
    assert group_episodes(pd.DataFrame(rows)).iloc[0].sell_fraction == pytest.approx(0.25)

def test_lag_days_sec_business_days():
    r = tx(date(2024,10,11)); r["accepted_at"] = datetime(2024,10,16,17,0,tzinfo=ET)
    assert group_episodes(pd.DataFrame([r])).iloc[0].lag_days == 2
```

  Integration tests in `test_build_decisions.py`:
  - `test_ignores_superseded_and_non_ps`: seed codes A, M, F and G, plus one superseded P, via factories. The result is 0 decisions.
  - `test_joint_filing_one_decision_two_owners`: one filing with owners (2000003, 2000004) and one P row gives 1 decision with 2 `decision_owners`.
  - `test_accessions_collected`: two filings three days apart give 1 decision whose `accessions` holds both, with `first_accession` = the earliest accepted.

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_episodes.py tests/integration/test_build_decisions.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): group trades into decisions (episodes)`.

---

### Task D3: Entry prices (filed and executed)

**Files:**
- Create: `backend/src/signals/analytics/entries.py`
- Test: `backend/tests/unit/test_entries.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Entry:
    date: date; price_adj: float; kind: Literal["open", "close", "reported", "close_fallback"]
    flags: tuple[str, ...] = ()

def filed_entry(accepted_at: datetime | None, filed_date: date, series: IssuerSeries) -> Entry | None
def executed_entry(trade_date: date, vwap: float | None, series: IssuerSeries) -> Entry | None
```

**`filed_entry`:**
- `accepted_at` is converted to ET and compared with `session_open_close(day)`:
  - On a trading day before the open → that day's open.
  - At or after the open and before the close → that day's close.
  - Otherwise → the next trading day's open.
- `None` acceptance is treated as 16:00 ET on `filed_date` and flagged `acceptance_unknown`.
- If the chosen day has no bar, step forward up to 5 trading days to the first bar (always its open) and flag `entry_gap`. If there's still none, return `None`.

**`executed_entry`:**
- The date is `trade_date` if it's a trading day, otherwise the next trading day.
- The price is `vwap × series.factor_on_or_before(trade_date)`, kind `reported`.
- Without a vwap, use that date's `close_adj`, kind `close_fallback`.
- With no price data at all, return `None`.

- [ ] **Step 1: Write the failing tests.** A synthetic `IssuerSeries` over 2024-03-25 to 2024-04-05, 2024-05-28 to 2024-06-07 and 2024-11-25 to 2024-12-06 has `open = 10`, `close = 11` and `adj_factor = 1` everywhere, except `adj_factor = 0.5` from 2024-05-28 to 2024-06-07.

```python
@pytest.mark.parametrize("accepted,expected", [
    (datetime(2024,3,28,8,15,tzinfo=ET), (date(2024,3,28), "open")),
    (datetime(2024,3,28,11,0,tzinfo=ET), (date(2024,3,28), "close")),
    (datetime(2024,3,28,16,5,tzinfo=ET), (date(2024,4,1), "open")),      # Good Friday skipped
    (datetime(2024,3,29,10,0,tzinfo=ET), (date(2024,4,1), "open")),      # SEC open, NYSE closed
    (datetime(2024,11,29,13,30,tzinfo=ET), (date(2024,12,2), "open")),   # after 13:00 early close
])
def test_filed_entry_timing(series, accepted, expected):
    e = filed_entry(accepted, accepted.date(), series); assert (e.date, e.kind) == expected

def test_filed_entry_unknown_acceptance(series):
    e = filed_entry(None, date(2024,3,28), series)
    assert (e.date, e.kind, e.flags) == (date(2024,4,1), "open", ("acceptance_unknown",))

def test_executed_entry_applies_split_factor(series):
    e = executed_entry(date(2024,6,3), 100.0, series); assert (e.price_adj, e.kind) == (50.0, "reported")

def test_executed_entry_weekend_trade(series):
    e = executed_entry(date(2024,6,1), 100.0, series); assert (e.date, e.price_adj) == (date(2024,6,3), 50.0)

def test_executed_entry_missing_price(series):
    e = executed_entry(date(2024,6,3), None, series); assert (e.price_adj, e.kind) == (5.5, "close_fallback")

def test_entry_none_without_prices():
    assert filed_entry(datetime(2024,3,28,8,0,tzinfo=ET), date(2024,3,28), empty_series()) is None
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_entries.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): filed and executed entry prices`.

---

### Task D4: Horizon returns, excess returns, lag cost

**Files:**
- Create: `backend/src/signals/analytics/returns.py`
- Test: `backend/tests/unit/test_returns.py`, `backend/tests/integration/test_decision_returns.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class HorizonResult:
    horizon: Horizon; exit_date: date; raw: float; excess_spy: float | None; excess_qqq: float | None
    excess_sector: float | None; complete: bool; exit_reason: Literal["horizon", "last_price"]

def horizon_returns(entry: Entry, direction: Literal["buy", "sell"], series: IssuerSeries, bench: BenchPanel,
                    sector_etf: str | None, as_of: date) -> list[HorizonResult]
def lag_cost(direction: Literal["buy", "sell"], filed: Entry | None, executed: Entry | None) -> float | None
def compute_decision_returns(session, *, decision_ids: Collection[int] | None = None, as_of: date) -> int
```

**`horizon_returns` rules:**
- **Exit:** the target exit is `add_trading_days(entry.date, N)`. The stock return is `close_adj(exit) / entry.price_adj − 1`.
- **Benchmarks:** each benchmark's entry is its `open_adj` on `entry.date` when `entry.kind == "open"`, otherwise its `close_adj`. Its exit is `close_adj(exit)`.
- **Incomplete:** if `as_of` is before the target exit, compute up to the last close on or before `as_of`, with `complete=False`.
- **Delisting:** if the series ends before the target exit and `as_of` is on or after it, exit at the last close with `exit_reason="last_price"` and `complete=True`.
- **Sales:** `raw = −stock_ret` and `excess = −(stock_ret − bench_ret)`.
- **Missing benchmark data:** a benchmark without bars on either date gives that excess as `None`.

**`lag_cost`:** `filed.price_adj / executed.price_adj − 1` for buys, with the sign flipped for sales. `None` when either entry is missing.

**`compute_decision_returns`:**
- It loads decisions, their issuer series and the bench panel once per issuer.
- For each basis (`filed` and `executed`) it writes 4 `decision_returns` rows (with `entry_kind` and `flags`), plus `decisions.lag_cost`. `sector_etf` is `SECTOR_ETF.get(issuer.sector)`.
- It replaces rows for the given decisions and returns the count.

- [ ] **Step 1: Write the failing tests** with synthetic series. The stock closes at 100 on 2024-01-02, 110 on 2024-02-01 (21 trading days later), and 5 as its last close on 2024-02-14, which is where the series ends. SPY closes at 400, then 404 on 2024-02-01.

```python
def test_buy_returns_and_excess(stock, bench):
    r = horizon_returns(Entry(date(2024,1,2), 100.0, "close"), "buy", stock, bench, None, date(2024,12,31))[0]
    assert (r.horizon, r.exit_date, r.complete) == ("1m", date(2024,2,1), True)
    assert r.raw == pytest.approx(0.10) and r.excess_spy == pytest.approx(0.09)

def test_sell_sign_flipped(stock, bench):
    r = horizon_returns(Entry(date(2024,1,2), 100.0, "close"), "sell", stock, bench, None, date(2024,12,31))[0]
    assert r.raw == pytest.approx(-0.10) and r.excess_spy == pytest.approx(-0.09)

def test_incomplete_horizon(stock, bench):
    r = horizon_returns(Entry(date(2024,1,2), 100.0, "close"), "buy", stock, bench, None, date(2024,1,12))[0]
    assert r.complete is False and r.exit_date == date(2024,1,12)

def test_delisted_exit_at_last_price(stock, bench):
    r3 = horizon_returns(Entry(date(2024,1,2), 100.0, "close"), "buy", stock, bench, None, date(2024,12,31))[1]
    assert (r3.exit_reason, r3.complete, r3.raw) == ("last_price", True, pytest.approx(-0.95))

def test_sector_excess_none_before_etf_history(stock2018, bench_without_xlc):
    r = horizon_returns(Entry(date(2018,1,2), 50.0, "close"), "buy", stock2018, bench_without_xlc, "XLC", date(2019,1,1))[0]
    assert r.excess_sector is None

def test_returns_across_split(split_stock, bench):
    # raw close 200 with factor 0.5 on entry day (adj 100); after a 2:1 split, raw 110 with factor 1.0
    e = executed_entry(date(2024,1,2), 200.0, split_stock)
    r = horizon_returns(e, "buy", split_stock, bench, None, date(2024,12,31))[0]
    assert e.price_adj == pytest.approx(100.0) and r.raw == pytest.approx(0.10)

def test_lag_cost():
    ex, fi = Entry(date(2024,1,2), 50.0, "reported"), Entry(date(2024,1,4), 55.0, "open")
    assert lag_cost("buy", fi, ex) == pytest.approx(0.10)
    assert lag_cost("sell", Entry(date(2024,1,4), 45.0, "open"), ex) == pytest.approx(0.10)
    assert lag_cost("buy", None, ex) is None
```

  Integration test `test_compute_decision_returns_rows`: seed one decision plus prices for 300 trading days. The result is 8 rows (2 bases × 4 horizons), and `decisions.lag_cost` is set.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): horizon returns, excess returns and disclosure lag cost`.

---

### Task D5: Insider copycat portfolio

**Files:**
- Create: `backend/src/signals/analytics/copycat.py`
- Test: `backend/tests/unit/test_copycat.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Lot: lot_id: int; issuer_cik: int; series: IssuerSeries; entry: Entry; sector_etf: str | None
@dataclass(frozen=True)
class SaleEvent: issuer_cik: int; entry: Entry; fraction: float

def copycat_nav(lots: Sequence[Lot], sales: Sequence[SaleEvent], bench: BenchPanel, start: date, end: date,
                *, hold_days: int = 252, min_weight: float = 0.05) -> pd.DataFrame
# index: trading days start..end; columns nav, spy, qqq, sector (all 1.0 on the first day), invested (Σw after that day)
```

**Algorithm.** This fixes the spec 9.4 semantics. Sales apply to every open lot of the same issuer.

```
dates = trading_days(start, end); W = {}                     # lot_id -> weight
for each t in dates[1:]:
    # start of day t
    add lots with entry.kind == "open" and entry.date == t   (w = 1; first return measured from entry.price_adj)
    apply sales with entry.kind == "open" and entry.date == t   (w *= 1 - fraction for lots of that issuer)
    drop lots whose series has no close at t (delisted: realized at last close, no return today)
    r_i = close_adj_i(t) / base_i - 1, where base_i = entry.price_adj on the lot's first return day,
          else close_adj_i(previous trading day)
    r_p = (Σ w_i r_i + max(0, 1 - Σ w) * r_spy(t)) / max(1, Σ w)
    sector: the same formula with r_i replaced by the lot's sector ETF return (SPY when sector_etf is None or missing)
    nav *= 1 + r_p ; spy/qqq track their own buy-and-hold ; invested[t] = Σ w
    # end of day t
    add lots with entry.kind in ("close", "reported", "close_fallback") and entry.date == t
    apply sales with those kinds and entry.date == t
    close lots where trading_days_between(entry.date, t) >= hold_days, or w < min_weight
```

- [ ] **Step 1: Write the failing tests** with hand-computed series over 2024-01-02 … 2024-01-08:

```python
def test_no_lots_tracks_spy(bench_up_1pct):
    nav = copycat_nav([], [], bench_up_1pct, date(2024,1,2), date(2024,1,4))
    assert list(nav["nav"].round(6)) == [1.0, 1.01, 1.0201]

def test_single_lot_full_weight(stock_10_11_11, bench_up_1pct):
    lot = Lot(1, 1000001, stock_10_11_11, Entry(date(2024,1,2), 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_up_1pct, date(2024,1,2), date(2024,1,4))
    assert nav.loc[date(2024,1,3), "nav"] == pytest.approx(1.10) and nav.loc[date(2024,1,4), "nav"] == pytest.approx(1.10)

def test_open_entry_earns_open_to_close(stock_open10_close105, bench_flat):
    lot = Lot(1, 1000001, stock_open10_close105, Entry(date(2024,1,3), 10.0, "open"), None)
    nav = copycat_nav([lot], [], bench_flat, date(2024,1,2), date(2024,1,3))
    assert nav.loc[date(2024,1,3), "nav"] == pytest.approx(1.05)

def test_two_lots_equal_weight(stock_up_10pct, stock_flat, bench_flat):
    lots = [Lot(1, 1, stock_up_10pct, Entry(date(2024,1,2), 10.0, "close"), None),
            Lot(2, 2, stock_flat, Entry(date(2024,1,2), 10.0, "close"), None)]
    assert copycat_nav(lots, [], bench_flat, date(2024,1,2), date(2024,1,3)).iloc[-1]["nav"] == pytest.approx(1.05)

def test_partial_sale_moves_money_to_spy(stock_flat_then_up10, bench_up_2pct_on_day4):
    lot = Lot(1, 1000001, stock_flat_then_up10, Entry(date(2024,1,2), 10.0, "close"), None)
    sale = SaleEvent(1000001, Entry(date(2024,1,3), 10.0, "close"), 0.5)
    nav = copycat_nav([lot], [sale], bench_up_2pct_on_day4, date(2024,1,2), date(2024,1,4))
    assert nav.loc[date(2024,1,4), "nav"] / nav.loc[date(2024,1,3), "nav"] - 1 == pytest.approx(0.06)

def test_lot_closes_after_hold_days(stock_up_10pct_daily, bench_up_1pct):
    lot = Lot(1, 1, stock_up_10pct_daily, Entry(date(2024,1,2), 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_up_1pct, date(2024,1,2), date(2024,1,5), hold_days=2)
    assert nav.loc[date(2024,1,5), "nav"] / nav.loc[date(2024,1,4), "nav"] - 1 == pytest.approx(0.01)

def test_min_weight_closes_lot(stock_flat_then_up10, bench_up_2pct_on_day4):
    lot = Lot(1, 1000001, stock_flat_then_up10, Entry(date(2024,1,2), 10.0, "close"), None)
    sale = SaleEvent(1000001, Entry(date(2024,1,3), 10.0, "close"), 0.96)       # w 1.0 -> 0.04 < 0.05 -> closed
    nav = copycat_nav([lot], [sale], bench_up_2pct_on_day4, date(2024,1,2), date(2024,1,4))
    assert nav.loc[date(2024,1,4), "nav"] / nav.loc[date(2024,1,3), "nav"] - 1 == pytest.approx(0.02)
    assert nav.loc[date(2024,1,4), "invested"] == 0

def test_delisted_lot_no_nan(stock_ends_0103, bench_up_1pct):
    lot = Lot(1, 1000001, stock_ends_0103, Entry(date(2024,1,2), 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_up_1pct, date(2024,1,2), date(2024,1,4))
    assert nav["nav"].notna().all()
    assert nav.loc[date(2024,1,4), "nav"] / nav.loc[date(2024,1,3), "nav"] - 1 == pytest.approx(0.01)

def test_sector_column_uses_etf(stock_flat, bench_xlk_up3_on_0103):
    lot = Lot(1, 1000001, stock_flat, Entry(date(2024,1,2), 10.0, "close"), "XLK")
    nav = copycat_nav([lot], [], bench_xlk_up3_on_0103, date(2024,1,2), date(2024,1,3))
    assert nav.loc[date(2024,1,3), "sector"] == pytest.approx(1.03) and nav.loc[date(2024,1,3), "nav"] == pytest.approx(1.0)
```

  Series fixtures (in `tests/unit/conftest.py` for this file):
  - `stock_10_11_11`: closes 10, 11, 11 on 01-02, 01-03, 01-04.
  - `stock_open10_close105`: on 01-03, open 10.0 and close 10.5.
  - `stock_up_10pct`: 10 then 11. `stock_flat`: 10 every day.
  - `stock_flat_then_up10`: 10, 10, 11.
  - `stock_up_10pct_daily`: 10, 11, 12.1, 13.31.
  - `stock_ends_0103`: 10, 10.5, and no bar after 01-03.
  - Benchmarks: `bench_up_1pct` has SPY and QQQ +1% a day. `bench_flat` has SPY and QQQ flat. `bench_up_2pct_on_day4` is flat except +2% on 01-04. `bench_xlk_up3_on_0103` is flat SPY and QQQ with XLK going 100 → 103 on 01-03.
  - Every `adj_factor` is 1.

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_copycat.py`. Expected: FAIL.

- [ ] **Step 3:** Implement per the algorithm, vectorizing per date over the open lots.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): insider copycat (calendar-time) portfolio`.

---

### Task D6: Window returns and risk

**Files:**
- Create: `backend/src/signals/analytics/windows.py`
- Test: `backend/tests/unit/test_windows.py`

**Interfaces:**
- `window_stats(nav: pd.DataFrame, as_of: date) -> list[WindowResult]`: always 4 results, in the order ytd, 1y, 3y, 5y.
  - **YTD:** from the last trading day of the previous year to `as_of`.
  - **1y/3y/5y:** trailing 252/756/1260 trading days. If the history is too short, every field is `None`.
  - `annualized = (1 + ret) ** (252 / n) − 1`, for 3y and 5y only.
  - `vol` = the standard deviation of daily nav returns × √252.
  - `max_drawdown = min(nav / cummax − 1)`.
  - `beta = cov(r, r_spy) / var(r_spy)`.
  - `time_invested_pct = mean(invested > 0)`, over the window.
- `risk_label(vol: float | None) -> RiskLabel | None`: below 0.20 is `low`, 0.20 through 0.40 inclusive is `medium`, above 0.40 is `high`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_5y_doubling():
    nav = geometric_nav(end=date(2024,12,31), n_returns=1260, total=2.0)
    w = {x.window: x for x in window_stats(nav, date(2024,12,31))}
    assert w["5y"].ret == pytest.approx(1.0) and w["5y"].annualized == pytest.approx(0.148698, abs=1e-6)

def test_ytd_from_previous_year_close():
    nav = nav_from({date(2023,12,29): 1.0, date(2024,6,28): 1.1})
    assert {x.window: x for x in window_stats(nav, date(2024,6,28))}["ytd"].ret == pytest.approx(0.10)

def test_short_history_none():
    w = {x.window: x for x in window_stats(geometric_nav(date(2024,12,31), 300, 1.1), date(2024,12,31))}
    assert w["3y"].ret is None and w["5y"].ret is None and w["1y"].ret is not None

def test_drawdown_beta_invested():
    dates = [date(2023, 12, 29), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    nav = nav_from_rows(dates=dates, nav=[1, 1.2, 0.9, 1.1], spy=[1, 1.1, 0.95, 1.05], invested=[0, 1, 1, 0])
    ytd = {x.window: x for x in window_stats(nav, date(2024, 1, 4))}["ytd"]    # the YTD window spans all 4 rows
    assert ytd.max_drawdown == pytest.approx(-0.25) and ytd.time_invested_pct == pytest.approx(0.5)
    r = pd.Series([0.01, -0.02, 0.03]); assert beta_of(2 * r, r) == pytest.approx(2.0)

@pytest.mark.parametrize("v,label", [(0.19, "low"), (0.20, "medium"), (0.40, "medium"), (0.41, "high"), (None, None)])
def test_risk_label(v, label):
    assert risk_label(v) == label
```

  `geometric_nav`, `nav_from` and `nav_from_rows` are test helpers. `beta_of` is a small public helper in `windows.py`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): window returns and risk metrics`.

---

### Task D7: Fund copycat portfolio

**Files:**
- Create: `backend/src/signals/analytics/funds.py`
- Test: `backend/tests/unit/test_fund_copycat.py`, `backend/tests/integration/test_fund_periods.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FundPeriodHoldings:
    period: date; start: date; start_kind: Literal["open", "close"]
    weights: dict[str, float]     # canonical symbol -> weight among priced SH (put_call '') positions, sums to 1
    coverage: float               # priced value / total SH value

def load_fund_periods(session, filer_cik: int, *, basis: Basis) -> tuple[list[FundPeriodHoldings], dict[str, IssuerSeries]]
def fund_copycat_nav(periods: Sequence[FundPeriodHoldings], panel: Mapping[str, IssuerSeries], bench: BenchPanel,
                     *, end: date) -> pd.DataFrame      # nav, spy, qqq, sector, coverage (the coverage in force that day)
def fund_quarterly_excess(nav: pd.DataFrame, starts: Sequence[date]) -> list[float]   # period return − SPY return
```

- **Start of each period's holdings:**
  - Executed basis: `start` = the quarter-end date, or the last trading day before it, with `start_kind="close"`.
  - Filed basis: `filed_entry(filing.accepted_at, filing.filed_date, spy_series)`, taking its date and kind.
- **Weights:** a symbol comes from `securities.ticker` (mapped). Positions without a mapping or without any price in the period are left out and the rest renormalized, and `coverage` records what was dropped.
- **Buy-and-hold within a period:** `nav(t) = nav(start) × Σ w_i · P_i(t) / P_i(start)`, where `P` is `close_adj`. If a holding's prices stop, its last price is carried forward.
- **Sector benchmark:** each symbol is swapped for its issuer's sector ETF (SPY when unknown), with the same weights.

- [ ] **Step 1: Write the failing tests:**
  - `test_two_stocks_half_each`: A goes 10 → 12 and B stays at 10, with weights 0.5 each, so nav at the end is `1.10`.
  - `test_rebalance_next_period`: period 2 starts at t2 with `{B: 1.0}`, and B rises 10% after t2, so the end nav is `1.10 × 1.10 = 1.21`.
  - `test_unpriced_excluded_coverage` (integration): reported values 40/40/20, with the third CUSIP unmapped. The weights are `{A: 0.5, B: 0.5}` and the coverage is `0.8`.
  - `test_filed_basis_holds_previous_until_filing` (integration): with two periods, on the filed basis the day before period 2's filing entry still holds period 1's weights.
  - `test_quarterly_excess`: a period return of 0.05 against SPY's 0.02 gives `[0.03]`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): fund copycat portfolio from 13F holdings`.

---

### Task D8: Profile stats and reliability ratings

**Files:**
- Create: `backend/src/signals/analytics/stats.py`
- Test: `backend/tests/unit/test_stats.py`, `backend/tests/integration/test_profile_stats.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ProfileSummary:
    n_decisions: int; n_buys: int; n_sells: int; n_complete: int; avg_roi_6m: float | None
    avg_roi_6m_raw: float | None; median_6m: float | None; hit_rate: float | None
    best_decision_id: int | None; worst_decision_id: int | None; avg_lag_days: float | None; avg_lag_cost: float | None

def summarize(decisions: pd.DataFrame, returns_6m: pd.DataFrame) -> ProfileSummary
def shrunk_mean(n: int, mean: float, mu: float, k: float) -> float
def percentile_ratings(values: pd.Series) -> pd.Series
def confidence_insider(n: int) -> Confidence | None
def confidence_fund(n: int) -> Confidence | None
def compute_profile_stats(session, *, owner_ciks: Collection[int] | None = None, as_of: date) -> int
def compute_fund_stats(session, *, filer_ciks: Collection[int] | None = None, as_of: date) -> int
```

- `summarize`: `returns_6m` rows have `decision_id, raw_return, excess_spy, is_complete`. Averages, median and hit rate use complete rows only.
- `percentile_ratings`: `round(100 × (rank − 1) / (n − 1))` over non-null values using average ranks, 50 when `n == 1`, and NaN stays NaN.
- The confidence functions return `None` when `n == 0`.

**`compute_profile_stats`.** For each owner, for each basis in (`filed`, `executed`) and each `include_10b5_1` in (False, True):
1. Summarize their decisions.
2. Build the copycat (D5) from their buy lots and sell events on that basis, then run `window_stats`. That produces 4 `profile_windows` rows.
3. `risk_label` comes from the 5y vol, falling back to the full-history vol.
4. `shrunk_mean` uses `μ` = the mean of complete 6m excess across all decisions on that basis, with each decision counted once.
5. `rating` is the percentile among insiders with `n_complete ≥ 1` on the same basis and toggle. The rating is `None` when `n_complete == 0`.
6. `primary_issuer_cik` is the issuer with the most decisions. `sector` is that issuer's sector.

It replaces rows for the given owners (or all) and returns the count.

**`compute_fund_stats`** does the same for tracked funds, using `fund_quarterly_excess` (n = quarters, `k = 4`) and `confidence_fund`. Its windows come from `fund_nav_daily`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_shrunk_mean():
    assert shrunk_mean(2, 0.10, 0.01, 5) == pytest.approx(0.0357142857)
    assert shrunk_mean(40, 0.10, 0.01, 5) == pytest.approx(0.09)

def test_percentile_ratings():
    assert list(percentile_ratings(pd.Series([0.01, 0.02, 0.03]))) == [0, 50, 100]
    assert list(percentile_ratings(pd.Series([0.5]))) == [50]
    assert percentile_ratings(pd.Series([0.1, float("nan")])).isna().tolist() == [False, True]

@pytest.mark.parametrize("n,c", [(0, None), (4, "low"), (5, "medium"), (15, "medium"), (16, "high")])
def test_confidence_insider(n, c): assert confidence_insider(n) == c

@pytest.mark.parametrize("n,c", [(0, None), (3, "low"), (4, "medium"), (12, "medium"), (13, "high")])
def test_confidence_fund(n, c): assert confidence_fund(n) == c

def test_summary_values():
    s = summarize(decisions_df(ids=[1, 2, 3, 4]),
                  returns_df([(1, 0.12, 0.10, True), (2, -0.03, -0.05, True), (3, 0.04, 0.02, True), (4, 0.5, 0.4, False)]))
    assert s.n_complete == 3 and s.avg_roi_6m == pytest.approx(0.0233333, abs=1e-6)
    assert s.hit_rate == pytest.approx(2 / 3) and s.median_6m == pytest.approx(0.02)
    assert (s.best_decision_id, s.worst_decision_id) == (1, 2)

def test_rating_none_without_complete_decisions(session):
    seed_owner_with_incomplete_decision(session)          # one decision, 6m not complete yet
    compute_profile_stats(session, as_of=date(2024, 3, 1))
    ps = session.get(ProfileStats, ("insider", 2000001, "filed", False))
    assert (ps.n_complete, ps.rating, ps.confidence, ps.avg_roi_6m) == (0, None, None, None)

def test_population_mean_counts_joint_decision_once(session):
    # joint decision (owners 2000003 and 2000004) with excess 0.30 and a single-owner decision (2000001) with 0.00
    seed_mu_world(session)
    compute_profile_stats(session, as_of=date(2025, 1, 2))
    ps = session.get(ProfileStats, ("insider", 2000001, "filed", False))
    assert ps.shrunk_mean == pytest.approx((1 * 0.0 + 5 * 0.15) / 6)

def test_four_rows_per_insider(session):
    seed_mu_world(session); compute_profile_stats(session, as_of=date(2025, 1, 2))
    n = session.scalar(select(func.count()).select_from(ProfileStats).where(ProfileStats.cik == 2000001))
    assert n == 4                                   # {filed, executed} x include_10b5_1 {False, True}
```

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): profile stats and shrinkage reliability ratings`.

---

### Task D9: Insider conviction rule

**Files:**
- Create: `backend/src/signals/analytics/allocation.py`
- Test: `backend/tests/unit/test_allocation.py`

**Interfaces:** `insider_high_conviction(stake_change_pct: float | None, value_usd: float | None, is_new_position: bool) -> bool`. It's true for `stake_change_pct >= 0.20`, `value_usd >= 1_000_000` or `is_new_position` (spec 9.7). Portfolio concentration helpers come from `signals.domain.portfolio` (foundation).

- [ ] **Step 1: Write the failing test:**

```python
def test_insider_high_conviction():
    assert insider_high_conviction(0.2, 10, False) and not insider_high_conviction(0.19, 999_999, False)
    assert insider_high_conviction(None, 1_000_000, False) and insider_high_conviction(None, 5, True)
    assert not insider_high_conviction(None, None, False)
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_allocation.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the test. Expected: pass.

- [ ] **Step 5: Commit** with message `feat(analytics): insider conviction rule`.

---

### Task D10: Badges

**Files:**
- Create: `backend/src/signals/analytics/badges.py`
- Test: `backend/tests/integration/test_badges.py`

**Interfaces:** `compute_badges(session, *, issuer_ciks: Collection[int] | None = None) -> int` recomputes `decisions.badges`, sets `form144_notices.matched_sale_accession`, and returns the number of decisions changed.

**Rules**, exactly:
- **`cluster_buy`:**
  - Only discretionary buys (`direction='buy'` and `not is_planned`) count.
  - For each such decision `d` in an issuer, look at the window `[d.first_trade_date, d.first_trade_date + 14 days]`.
  - If the window holds at least 3 distinct `owner_group`s, every decision in it gets the badge.
- **`late_filing`:** `sec_business_days_between(first_trade_date, accepted_at ET date) >= 3`.
- **`first_buy_2y`:** a discretionary buy with no earlier discretionary buy by the same `owner_group` in the same issuer whose `first_trade_date` is within 730 days before this one.
- **`dip_buy`:** on buys, `close_adj(prev_trading_day(first_trade_date)) / close_adj(60 trading days before that) − 1 <= −0.20`.
- **`big_stake`:** buys where `insider_high_conviction(...)` is true.
- **`form144_matched`:**
  - A sale decision whose owners include a Form 144 `filer_cik` for the same issuer, with `first_trade_date` in `[notice filed_date, filed_date + 90 days]`.
  - The earliest match wins. The notice's `matched_sale_accession` is set to the decision's `first_accession`.
- **`top_exec`:** any owner's `owner_roles.roles` for that issuer includes CEO, CFO or President.

- [ ] **Step 1: Write the failing tests** (factory-seeded decisions):
  - `test_cluster_three_groups_within_14_days`: dates 05-01, 05-08 and 05-14 (2024) for groups g1, g2 and g3 all get the badge.
  - `test_cluster_needs_window_of_14_days`: dates 05-01, 05-08 and 05-16 get no badge.
  - `test_joint_group_counts_once`: groups `2000003|2000004` and `2000001` within 5 days make 2 groups, so no badge.
  - `test_late_filing_columbus_day`: trade 2024-10-10. Accepted 2024-10-15 is not late; accepted 2024-10-16 is late.
  - `test_first_buy_2y`: a prior buy on 2022-05-01 and a new one on 2024-05-02 give the badge. A prior buy on 2022-06-01 gives none.
  - `test_dip_buy_threshold`: −21% gives the badge and −19% doesn't.
  - `test_big_stake`: stake 0.2 gets it; 0.19 at $999,999 doesn't; $1,000,000 does.
  - `test_form144_match_window`: a notice filed 2024-03-01 and a sale on 2024-04-15 match, and `matched_sale_accession` is set. A sale on 2024-06-15 doesn't match.
  - `test_top_exec_from_roles`: an owner with role `CEO` at the issuer gets the badge.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_badges.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): decision badges (cluster, late, first buy, dip, big stake, 144, top exec)`.

---

### Task D11: Positions

**Files:**
- Create: `backend/src/signals/analytics/positions.py`
- Test: `backend/tests/integration/test_positions.py`

**Interfaces:** `build_positions(session, *, owner_ciks: Collection[int] | None = None) -> int`.

- For each owner (every CIK in a row's `owner_group`) and each `(issuer_cik, security_title, direct_indirect)`, take the latest non-superseded, non-derivative transaction or holding row.
- "Latest" means by filing `accepted_at` (else `filed_date`), then `row_no`.
- A row counts if it has `shares_owned_after` (transactions) or `shares_owned` (holdings).
- It writes `positions(shares, as_of_date = the filing's filed_date, last_accession)` and replaces rows for those owners.

- [ ] **Step 1: Write the failing tests:**
  - `test_latest_shares_win`: a January filing with shares-after 1000, then a March one with 1500, gives 1500 as of March.
  - `test_superseded_ignored`: a later row that's superseded doesn't count.
  - `test_form3_holdings_count`: a holding row of 5000 shares gives a position of 5000.
  - `test_derivatives_excluded`.
  - `test_joint_rows_attributed_to_each_owner`: a group `2000003|2000004` gives two position rows.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(analytics): reconstructed insider positions`.

---

### Task D12: Orchestration, curve service, feed refresh, jobs

**Files:**
- Create: `backend/src/signals/analytics/run.py`
- Modify: `backend/src/signals/analytics/curves.py`, `backend/src/signals/analytics/jobs.py` (your stubs)
- Test: `backend/tests/integration/test_analytics_run.py`

**Interfaces:**
- `RunResult(decisions: int, returns: int, badges: int, insider_profiles: int, fund_profiles: int, seconds: float)`
- `run_full(session_factory, *, as_of: date, include_funds: bool = True, progress: Callable[[str], None] | None = None) -> RunResult`. The steps, each committed as one transaction:
  1. `build_positions`
  2. `build_decisions`
  3. `compute_decision_returns`
  4. `compute_badges`
  5. `compute_profile_stats`
  6. If `include_funds`:
     - `_fund_changes(session)`.
     - For each tracked fund and each basis, `fund_copycat_nav`. Write `fund_nav_daily`, and `profile_windows` with `include_10b5_1 = False`.
     - `compute_fund_stats`.
  7. `refresh_feed_items`:
     - `feed_items.badges` = the union of the badges of decisions whose `accessions` contain the feed item's accession.
     - `sector` = the issuer's sector.
     - `market_cap_usd = shares_outstanding × latest close_adj`.
  8. `set_state(session, "analytics_version", {"as_of": …, "run_at": …})`.
- `run_incremental(session_factory, *, issuer_ciks, owner_ciks, as_of) -> RunResult`: the same steps limited to those issuers and owners. It still refreshes the population mean and all ratings on the same basis, because percentiles are relative.
- `insider_curve(session, cik, *, basis, include_10b5_1, as_of) -> Curve`:
  - Builds the lots and sales for that owner and runs `copycat_nav` from the first entry date to `as_of`.
  - `points` = nav, spy, qqq and sector, each divided by its first value.
  - `windows = window_stats(nav, as_of)` and `coverage_pct = None`.
  - It's cached with `functools.lru_cache(maxsize=256)` on `(cik, basis, include_10b5_1, as_of, analytics_version.run_at)`.
  - With no decisions it returns a `Curve` with empty `points` and 4 all-`None` windows.
- `fund_curve(session, cik, *, basis, as_of) -> Curve` reads `fund_nav_daily` and the windows. It raises `LookupError("fund not tracked")` when the fund isn't tracked.
- Jobs: `analytics_full` with `cron={"hour": 2, "minute": 0}`, calling `run_full(as_of=today_et)`, and `analytics_incremental` on request with params `issuer_ciks` and `owner_ciks`.

- [ ] **Step 1: Write the failing tests.** They share a fixture `seeded_world(session)` built with the factories:
  - Issuer ACME (Technology) with prices from 2023-01-03 to 2024-12-31, rising 0.1% a day.
  - SPY, QQQ and XLK prices over the same range.
  - Owners g1 (CEO), g2 and g3 buying on 2024-02-01, 2024-02-06 and 2024-02-12.
  - g1 selling on 2024-08-01.
  - One tracked fund with 2 periods.

  The tests:
  - `test_run_full_counts`: `decisions == 4`, `returns == 32`, and the three February buys carry `cluster_buy`. Every owner has 4 `profile_stats` rows. The fund has `fund_nav_daily` rows. The feed items for the buy filings include `cluster_buy`.
  - `test_run_full_idempotent`: a second run gives identical counts and decision badges.
  - `test_incremental_only_touches_given_issuers`: add issuer 2 with its own decision, then run incremental for issuer 2 only. Issuer 1's `decision_returns` rows are unchanged (compare the row sets).
  - `test_insider_curve_normalized`: the first row of `points` is 1.0 for every column, and `len(windows) == 4`.
  - `test_fund_curve_untracked_raises`: `LookupError`.
  - `test_jobs_registered`: `JOBS["analytics_full"].cron == {"hour": 2, "minute": 0}` and `"analytics_incremental" in JOBS`.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_analytics_run.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest -q`. Expected: the whole backend suite passes.

- [ ] **Step 5: Commit** with message `feat(analytics): full/incremental runs, curve service and jobs`.
