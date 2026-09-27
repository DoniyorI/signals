# Workstream E: API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every endpoint of the foundation's API contract against the canonical and derived tables. That includes keyset pagination, CSV export, ticker-or-CIK company lookup, the curve service and the health report.

**Architecture:**
- The routers (foundation stubs) call query functions in `signals/api/queries/*.py`.
- Queries use SQLAlchemy Core or ORM selects and return the foundation's Pydantic schemas.
- The API reads only. The single write path is watchlists and job requests.
- Performance curves come through the `CurveService` dependency, which tests override with a fake.

**Tech Stack:** FastAPI 0.141, SQLAlchemy 2.1, Pydantic 2.13, pytest with `fastapi.testclient.TestClient`.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, section 10 (endpoints) and sections 9.6–9.8 (the meaning of fields).

## Global Constraints

Everything in `00-overview.md` › Global Constraints. On top of that:
- Work on branch `ws/e-api`. The router modules in `api/routers/` are your stubs. Create `api/pagination.py`, `api/csv.py`, `api/queries/*.py` and the tests.
- Don't change `api/schemas.py`, `api/main.py` or `api/deps.py`. If the contract looks wrong, stop and report it.
- The API never calls external services and never computes analytics beyond read-side aggregation. Tests override `get_curve_service`.
- `limit` defaults to 50 with a maximum of 500. Invalid cursors or ids return 400. Unknown entities return 404. An unknown job kind returns 422.
- Before starting, run `docker compose up -d db`.

## Review Focus

- Overview item 1 (ticker changes and reuse): E4 `test_company_lookup_by_old_and_reused_ticker`.
- Item 3 (empty profiles): E3 `test_insider_header_without_stats`.

## Interfaces consumed (from the foundation)

- `signals.api.schemas` (every model), `signals.api.deps` (`get_db`, `get_curve_service`, `CurveService`)
- `signals.analytics.types` (`Curve`, `WindowResult`)
- `signals.domain.tickers` (`canonical_symbol`, `issuer_for_symbol`, `current_symbol`, `ticker_intervals`)
- `signals.domain.portfolio` (`effective_n`, `top5_weight`, `allocation_slices`, `fund_high_conviction`)
- `signals.domain.accession.filing_index_url`, `signals.domain.types` (`CODE_LABELS`, `FUND_FORMS`, `STAKE_FORMS`, `INSIDER_FORMS`, `Role`)
- `signals.domain.calendars` (`ET`, `now_et`)
- `signals.jobs` (`request_job`, `load_all_jobs`), the models, the factories

## Interfaces produced

- `signals.api.pagination`: `encode_cursor(values: dict) -> str` and `decode_cursor(s: str | None) -> dict | None`. Invalid input raises `HTTPException(400, "invalid cursor")`.
- `signals.api.csv`: `csv_response(rows: Sequence[BaseModel], filename: str) -> Response`. Nested models flatten to dotted keys (`issuer.name`), and lists are joined with `;`.
- `signals.api.queries.common`: `issuer_ref(session, cik) -> IssuerRef`, `sec_url(cik, accession) -> str`, `latest_close(session, symbol) -> tuple[float, date] | None`, `rating_of(stats_row) -> Rating`.
- The rest is internal. The OpenAPI document is the external contract.

## Test seed world (`backend/tests/api/seed.py`)

`seed_world(session) -> SeedIds` builds this fixed, fictional dataset with the factories:

- **Issuers:**
  - 1000001 `Acme Corp` (ACME, Technology)
  - 1000002 `Globex Inc` (GBX until 2022-06-09, then GLBX, Communication Services)
  - 1000003 `Old Co` (XYZ until 2018-12-31, then XYZA)
  - 1000004 `New Co` (XYZ from 2020-05-01)
- **Owners:**
  - 2000001 `Doe Jane` (CEO of Acme)
  - 2000002 `Roe Richard` (director of Acme and Globex)
  - 2000003 `Acme Holdings LP` and 2000004 `Smith John` (a joint 10%-owner group)
  - 2000005 `New Person` (one decision, not complete)
- **Fund:** 3000001 `Example Capital Management`, tracked, with periods 2024-03-31 and 2024-06-30. It holds ACME (CUSIP `000000AA1`) and GLBX (`000000BB2`), and exits `000000CC3`.
- **Feed items:** 6 of them (4 buys and sells, one 13F-HR, one Form 144), with accepted times 2024-06-03 through 2024-06-07.
- **Analytics rows:**
  - Decisions, and decision returns for both bases.
  - `profile_stats` and `profile_windows` for 2000001, 2000002 and the fund. None for 2000005.
  - Positions for 2000001.
  - Prices for ACME, GLBX and SPY.
  - Form 144 notices (one matched, one pending).
  - One SCHEDULE 13D stake on Acme.

`FakeCurves` returns a `Curve` with 3 points (1.0, 1.05 and 1.10 for nav, and 1.0, 1.01 and 1.02 for spy, qqq and sector) and 4 windows with `ret` values 0.1, 0.2, None and None. It raises `LookupError` for fund 3999999.

---

### Task E1: Pagination, CSV and shared query helpers

**Files:**
- Create: `backend/src/signals/api/pagination.py`, `api/csv.py`, `api/queries/__init__.py`, `api/queries/common.py`, `backend/tests/api/__init__.py`, `backend/tests/api/seed.py`, `backend/tests/api/conftest.py`
- Test: `backend/tests/api/test_common.py`

**Interfaces:** as listed above. `tests/api/conftest.py` provides:
- `api(session)`: a `TestClient` with `get_db` overridden to the test session and `get_curve_service` overridden to `FakeCurves()`.
- `world(session)`: returns `seed_world(session)`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_cursor_roundtrip():
    c = encode_cursor({"a": "2024-06-07T16:00:00-04:00", "k": "0002000001-24-000009"})
    assert decode_cursor(c) == {"a": "2024-06-07T16:00:00-04:00", "k": "0002000001-24-000009"}
    assert decode_cursor(None) is None
    with pytest.raises(HTTPException): decode_cursor("not-base64!")

def test_csv_flattens():
    r = csv_response([FeedItemOut.model_validate(sample_feed_item())], "feed.csv")
    head = r.body.decode().splitlines()[0].split(",")
    assert r.media_type == "text/csv" and "issuer.name" in head and "badges" in head

def test_seed_world_builds(world, session):
    assert session.get(Issuer, 1000002).name == "Globex Inc"
```

- [ ] **Step 2:** Run `uv run pytest tests/api/test_common.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): pagination, CSV export, query helpers and test seed world`.

---

### Task E2: Feed endpoints

**Files:**
- Modify: `backend/src/signals/api/routers/feed.py`
- Create: `backend/src/signals/api/queries/feed.py`
- Test: `backend/tests/api/test_feed.py`

**Behavior:**
- **Order:** `(accepted_at DESC NULLS LAST, accession_no DESC)`. The cursor is `{"a": accepted_at ISO or null, "k": accession_no}`.
- **Form families:** `3`, `4` and `5` each include their `/A`. `144` means `144` and `144/A`. `13F` means `FUND_FORMS`. `13D` means `SCHEDULE 13D` and its `/A`. `13G` works the same way.
- **Filters:**
  - `codes` and `badges` use array overlap.
  - `roles` matches `top_role`.
  - `include_10b5_1=false` keeps only rows whose `plan_10b5_1` is `none` or NULL.
  - `trade_from` and `trade_to` apply to `first_trade_date`, and `filed_from` and `filed_to` to `filed_date`.
  - `owner_cik` matches when the CIK is in `owner_ciks`.
- **Output:** `FeedItemOut.owners` zips `owner_ciks` with `owner_names.split("; ")`, and `sec_url = filing_index_url(owner_ciks[0] or issuer_cik, accession_no)`.
- **`/feed/summary?date=`** (defaults to today in ET) covers feed items with `filed_date = date`:
  - `counts_by_form`.
  - `top_buys` and `top_sells`: the top 5 by `value_usd`.
  - `clusters`: decisions with `cluster_buy` whose `first_trade_date` falls in `[date − 14 days, date]`, grouped by issuer into `start_date`, `end_date`, `owner_count` (distinct groups) and `total_value_usd`.
  - `late_filings`: that day's feed items that carry `late_filing`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_order_and_pagination(api, world):
    p1 = api.get("/api/feed", params={"limit": 4}).json()
    p2 = api.get("/api/feed", params={"limit": 4, "cursor": p1["next_cursor"]}).json()
    accs = [i["accession_no"] for i in p1["items"] + p2["items"]]
    assert len(accs) == 6 == len(set(accs)) and p2["next_cursor"] is None
    ts = [i["accepted_at"] for i in p1["items"]]; assert ts == sorted(ts, reverse=True)

@pytest.mark.parametrize("params,expected", [
    ({"direction": ["buy"]}, world_buy_accessions), ({"forms": ["13F"]}, world_13f_accessions),
    ({"include_10b5_1": "false"}, world_non_planned_accessions), ({"min_value": 1_000_000}, world_big_accessions),
    ({"owner_cik": 2000002}, world_roe_accessions), ({"badges": ["cluster_buy"]}, world_cluster_accessions)])
def test_filters(api, world, params, expected):
    got = {i["accession_no"] for i in api.get("/api/feed", params=params).json()["items"]}
    assert got == expected(world)

def test_csv(api, world):
    r = api.get("/api/feed", params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv") and r.text.count("\n") == 7   # header + 6 rows

def test_invalid_cursor_400(api): assert api.get("/api/feed", params={"cursor": "zzz"}).status_code == 400

def test_summary(api, world):
    s = api.get("/api/feed/summary", params={"date": "2024-06-05"}).json()
    assert s["counts_by_form"] == world.counts_on_0605 and [i["accession_no"] for i in s["top_buys"]] == world.top_buys_0605
```

  The `world_*` expectations are properties on `SeedIds`, computed once in `seed.py` from the seed definitions.

- [ ] **Step 2:** Run `uv run pytest tests/api/test_feed.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): feed and daily summary endpoints`.

---

### Task E3: Insider endpoints

**Files:**
- Modify: `backend/src/signals/api/routers/insiders.py`
- Create: `backend/src/signals/api/queries/insiders.py`
- Test: `backend/tests/api/test_insiders.py`

**Behavior:**
- **Header:**
  - An unknown `owners` row returns 404.
  - `roles` come from `owner_roles`, with issuer refs carrying the current tickers.
  - Stats come from `profile_stats(kind='insider', cik, basis, include_10b5_1)`. When the row is missing, return `rating = Rating(score=None, confidence=None, n=0)`, every metric `None`, and counts from `decision_owners` (`n_decisions`, `n_buys`, `n_sells`).
  - `best` and `worst` are `DecisionOut`s. `fund_cik` is set when `fund_managers` has the same CIK.
- **Decisions:**
  - The owner's decisions, filtered by `include_10b5_1` (`is_planned = false` unless it's true) and `direction`.
  - Ordered by `(first_trade_date DESC, id DESC)`.
  - `returns` holds 4 `HorizonReturn`s for the requested basis, and `sec_url` uses `first_accession`.
- **Transactions:**
  - Rows whose accession has a `filing_owners` row for this CIK. Superseded rows appear only when `include_superseded=true`.
  - Ordered by `(transaction_date DESC NULLS LAST, accession_no DESC, row_no)`.
  - `code_label` comes from `CODE_LABELS`, and `footnotes` is the list of footnote texts.
- **Performance:**
  - `service.insider_curve(...)` becomes `PerformanceOut`: the points map to `CurvePoint`, and each `WindowResult` maps to `WindowStat` field for field.
- **Holdings:**
  - `positions` plus `latest_close` for the issuer's current symbol: `value_usd = shares × close` and `weight = value / total`.
  - `by_sector` and `by_issuer` use `allocation_slices`, alongside `effective_n` and `top5_weight`.
  - `derivatives` holds the derivative holding rows, with `value_usd=None`.
- **Form 144:**
  - Notices where `filer_cik = cik`.
  - `status` is `matched` when `matched_sale_accession` is set, `expired` when `approx_sale_date + 90 days < today`, and otherwise `pending`.

- [ ] **Step 1: Write the failing tests:**
  - `test_header_with_stats`: for 2000001 on the filed basis, the rating score and confidence equal the seeded values, and `roles[0].roles` contains `CEO`.
  - `test_insider_header_without_stats`: 2000005 returns 200 with `rating == {"score": None, "confidence": None, "n": 0}`, `avg_roi_6m is None` and `n_decisions == 1`.
  - `test_unknown_insider_404`.
  - `test_decisions_basis_and_toggle`: the default excludes the seeded planned decision, and `include_10b5_1=true` includes it. `returns` differ between the filed and executed bases.
  - `test_transactions_superseded_hidden`.
  - `test_performance_uses_curve_service`: `points[-1]["nav"] == 1.10`, and the `windows` returned from the `FakeCurves` data are ordered ytd, 1y, 3y, 5y.
  - `test_holdings_values`: ACME has 11,000 shares at a latest close of 10.0, giving `value_usd == 110000.0`. `effective_n == 1.0`.
  - `test_form144_status`: the seeded matched notice returns `matched`, and the pending one returns `pending`.

- [ ] **Step 2:** Run `uv run pytest tests/api/test_insiders.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): insider profile endpoints`.

---

### Task E4: Company endpoints

**Files:**
- Modify: `backend/src/signals/api/routers/companies.py`
- Create: `backend/src/signals/api/queries/companies.py`
- Test: `backend/tests/api/test_companies.py`

**Behavior:**
- **`/companies/{ref}`:**
  - An all-digit `ref` is a CIK. Otherwise `issuer_for_symbol(session, canonical_symbol(ref))`, which is the current holder, or else the latest holder. Unknown returns 404.
  - `former_tickers` = the interval symbols other than the current one, newest first.
  - `market_cap_usd = shares_outstanding × latest close`.
  - `net_buying`, for 3m, 6m and 12m windows ending today: from discretionary decisions, `buys_usd`, `sells_usd`, `net_usd = buys − sells`, and the counts of distinct buying and selling groups.
- **`/prices`:**
  - Bars come from each interval's symbol within its interval (raw OHLC plus `adj_close`), sorted by date.
  - The default range is the last 3 years.
  - Markers:
    - `buy` and `sell` at `first_trade_date`, labelled like `"Buy $1.2M · Doe Jane"`.
    - `form144` at `filed_date`.
    - `stake` at the event date (or filed date).
    - `cluster`, one per cluster start.
- **`/insiders`:** a roster from `owner_roles` for the issuer, with the last decision date, net 12-month USD, the decision count, and the rating (filed basis, `include_10b5_1` as requested).
- **`/institutions`:**
  - `period` defaults to the latest period with `fund_position_changes` for any CUSIP whose `securities.issuer_cik` is this company.
  - Rows are ordered by `value_usd` descending, excluding EXIT from the rows. `exit_count` counts the EXITs.
  - `periods_available` is sorted descending.
- **`/stakes`:** `ownership_stakes` for the issuer, newest first, filtered by `current_only`.
- **`/form144`:** the issuer's notices, filtered by `status`.

- [ ] **Step 1: Write the failing tests:**
  - `test_lookup_by_cik_and_ticker`: `/api/companies/1000001` and `/api/companies/acme` both give the Acme header.
  - `test_company_lookup_by_old_and_reused_ticker`:
    - `/api/companies/GBX` resolves to 1000002, with `former_tickers == ["GBX"]` and `ticker == "GLBX"`.
    - `/api/companies/XYZ` resolves to 1000004 (New Co, the current holder).
  - `test_unknown_company_404`.
  - `test_prices_and_markers`: the bar count equals the seeded trading days, and the marker kinds include `buy`, `sell`, `form144` and `stake`.
  - `test_institutions_latest_period`: `period == "2024-06-30"`, `exit_count == 0` for ACME (the exit is for CUSIP `000000CC3`), and the ACME row's `change` equals the seeded value.
  - `test_net_buying_12m`: `buys_usd` equals the sum of the seeded discretionary buy values within 12 months.

- [ ] **Step 2:** Run `uv run pytest tests/api/test_companies.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): company endpoints with ticker-or-CIK lookup`.

---

### Task E5: Fund endpoints

**Files:**
- Modify: `backend/src/signals/api/routers/funds.py`
- Create: `backend/src/signals/api/queries/funds.py`
- Test: `backend/tests/api/test_funds.py`

**Behavior:**
- **Header:**
  - `value_history`: per period, the sum of effective `fund_positions.value_usd` and the count of rows with `put_call=''`, ascending.
  - `rating` from `profile_stats(kind='fund', basis='filed', include_10b5_1=false)`. `windows` from `profile_windows`.
  - `coverage_pct` = the latest `fund_nav_daily.coverage`, filed basis.
  - `insider_cik` is set when `owners` has the same CIK.
- **Holdings:**
  - `period` defaults to the latest.
  - `rows` = non-EXIT `fund_position_changes` joined to `securities` and issuer sectors, ordered by `value_usd` descending.
  - `exits` = the EXIT rows.
  - `high_conviction` via `fund_high_conviction`, then `by_sector`, `effective_n` and `top5_weight` over the weights.
- **Performance:** `service.fund_curve`. A `LookupError` becomes 404 with detail `"performance is available for tracked funds only"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_fund_header`: `value_history` has 2 points, and the `latest_positions` value is as seeded.
  - `test_fund_holdings_rows_and_exits`: 2 rows plus 1 exit, and `high_conviction` on the ACME row equals the seeded expectation.
  - `test_fund_performance_404_untracked`: `/api/funds/3999999/performance` returns 404.
  - `test_unknown_fund_404`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): fund endpoints`.

---

### Task E6: Screener

**Files:**
- Modify: `backend/src/signals/api/routers/screener.py`
- Create: `backend/src/signals/api/queries/screener.py`
- Test: `backend/tests/api/test_screener.py`

**Behavior:**
- **Insiders:**
  - Rows come from `profile_stats` (kind `insider`, requested basis and toggle), joined to `owners`, the primary issuer, `owner_roles` (roles at the primary issuer), and `profile_windows` pivoted to `{"ytd","1y","3y","5y"}` returns.
  - Filters:
    - `roles` overlaps the roles at the primary issuer.
    - `sectors` matches `profile_stats.sector`.
    - `n_complete >= min_decisions`.
    - `last_trade_date` falls within the range.
    - `rating >= min_rating`.
    - `confidence` is in the list.
    - The return for `window` is between `min_return` and `max_return`.
    - `risk_label` is in `risk`.
  - Sort keys are `rating`, `avg_roi_6m`, `hit_rate`, `n_decisions`, `last_trade_date` and `return` (meaning the chosen window's return). NULLs sort last. The cursor is `{"v": sort value, "c": cik}`.
- **Funds:** the same over `fund_managers` joined with `profile_stats(kind='fund')`, with `tracked_only`.

- [ ] **Step 1: Write the failing tests:**
  - `test_default_sort_rating_desc`: the order is `[2000001, 2000002]`, as the seeded ratings imply.
  - `test_filters_role_and_min_rating`: `roles=["CEO"]` returns only 2000001, and `min_rating=99` returns an empty list.
  - `test_window_return_filter`: with `window="1y"` and `min_return=0.15`, only profiles whose seeded 1y return is at least 0.15 come back.
  - `test_pagination_stable`: with `limit=1`, following `next_cursor` gives both rows with no repeats.
  - `test_funds_tracked_only`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): insider and fund screeners`.

---

### Task E7: Compare and search

**Files:**
- Modify: `backend/src/signals/api/routers/compare.py`, `backend/src/signals/api/routers/search.py`
- Create: `backend/src/signals/api/queries/compare.py`, `backend/src/signals/api/queries/search.py`
- Test: `backend/tests/api/test_compare_search.py`

**Behavior:**
- **Compare:**
  - `ids` are comma-separated `insider:<cik>` or `fund:<cik>` values, 1 to 4 of them. Anything else returns 400.
  - Each profile gets its stats, windows and curve from the service.
  - Curves are rebased so every profile starts at 1.0 on the latest common first date.
  - Allocation comes from holdings (insiders) or latest fund sectors (funds).
- **Search:**
  - `q` has at least 2 characters.
  - **Companies:** an exact canonical-ticker match (score 1.0) plus `similarity(issuers.name, q) > 0.2`.
  - **Insiders:** `similarity(owners.name, q)`. **Funds:** `similarity(fund_managers.name, q)`.
  - An all-digit `q` also matches CIKs exactly (score 1.0).
  - Each group is sorted by score descending and cut to `limit`.
  - Subtitles:
    - Insider: `"<top role> · <primary issuer ticker>"`.
    - Company: `"<ticker> · <sector>"`.
    - Fund: `"13F · <$X.XB AUM>"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_search_by_ticker`: for `q=acme`, `companies[0].cik == 1000001` with `score == 1.0`.
  - `test_search_partial_name`: `q=doe` puts `2000001` among the insiders.
  - `test_search_by_cik`: `q=3000001` puts the fund first in the funds group.
  - `test_search_too_short`: `q=a` returns 422.
  - `test_compare_two`: `ids=insider:2000001,fund:3000001` returns 2 profiles whose curves both start at 1.0.
  - `test_compare_invalid`: `ids=bogus:1` returns 400, and 5 ids return 400.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): compare and search`.

---

### Task E8: Watchlists

**Files:**
- Modify: `backend/src/signals/api/routers/watchlists.py`
- Create: `backend/src/signals/api/queries/watchlists.py`
- Test: `backend/tests/api/test_watchlists.py`

**Behavior:**
- Everything is scoped to `user_id = 1`.
- **Create:** POST returns 201 with a `WatchlistOut`. A duplicate name returns 409.
- **Add item:** validates that the entity exists (the `owners` table for `insider`, `issuers` for `company`, `fund_managers` for `fund`), returning 404 otherwise. Adding an item twice is a no-op.
- **Delete item:** returns 204. Deleting a whole watchlist cascades to its items.
- **Activity:** feed items where `issuer_cik` is a watched company, or `owner_ciks` overlaps watched insiders or funds. Same order and pagination as the feed.

- [ ] **Step 1: Write the failing tests:**
  - `test_crud`: create, list, get, delete, and then get returns 404.
  - `test_duplicate_name_409`.
  - `test_add_remove_items_and_404_unknown`.
  - `test_activity_matches_watched`: watching Acme (company) and 3000001 (fund) returns exactly those feed items.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(api): watchlists and watchlist activity`.

---

### Task E9: Health and jobs

**Files:**
- Modify: `backend/src/signals/api/routers/health.py`, `backend/src/signals/api/routers/jobs.py`
- Create: `backend/src/signals/api/queries/health.py`
- Test: `backend/tests/api/test_health_jobs.py`

**Behavior:**
- **`jobs`:** for every kind seen in `ingest_runs.job` or `job_requests.kind`, the latest start, finish, status and error.
- **Feed delay:** over `filings` with `source='feed'` and `first_seen_at` in the last 24 hours, the seconds `first_seen_at − accepted_at`. Report p50 and p95 by linear interpolation. `last_filing_seen_at` is the latest `first_seen_at`.
- **`parse_errors`:** the latest 50 filings with `parse_status='error'`.
- **`backfill`:** one `BackfillStep` per latest `backfill_*` job request. `done_units` and `total_units` come from `progress["done_units"]` and `progress["total_units"]` when present; otherwise `done_units` is `len(progress.get("datasets_done", []))`.
- **`coverage`:**
  - `issuers_with_sector_pct` over issuers that have transactions.
  - `cusip_value_mapped_pct` over the latest period's effective positions, weighted by value.
  - `decisions_with_prices_pct`: decisions that have any filed-basis row.
  - `decisions_last_price_exit_pct`: filed-basis 6m rows with `exit_reason='last_price'`.
- **`sec_blocked_until`** comes from `app_state`.
- **`status`:**
  - `error` if SEC is blocked (until a time in the future), or if the last live poll success is more than 30 minutes old during 06:00–22:00 on an SEC business day.
  - Otherwise `warn` if there are parse errors in the last 24 hours.
  - Otherwise `ok`.
- **Jobs endpoints:** `POST /api/jobs` validates the kind against `load_all_jobs()` (422 for an unknown kind), calls `request_job`, and returns 202. `GET /api/jobs` returns the latest `limit` requests.

- [ ] **Step 1: Write the failing tests:**
  - `test_feed_delay_percentiles`: seed feed filings with delays `[30, 60, 90, 120]` seconds. The result is `p50 == 75.0` and `p95 == pytest.approx(115.5)`.
  - `test_parse_errors_listed_and_warn`.
  - `test_blocked_is_error`: `app_state sec_blocked_until` set in the future gives `status == "error"` and a non-null `sec_blocked_until`.
  - `test_jobs_post_and_list`: POSTing `backfill_all` returns 202 and GET lists it. Posting `nope` returns 422. Register a fake `backfill_all` job in the test registry if the real modules aren't loaded.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest -q`. Expected: the whole backend suite passes. Also run `uv run signals openapi --out /tmp/o.json && diff /tmp/o.json ../frontend/src/api/openapi.json`. Expected: no diff, meaning the contract is unchanged.

- [ ] **Step 5: Commit** with message `feat(api): health report and job requests`.
