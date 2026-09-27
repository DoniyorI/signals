# Workstream C: Reference Data and Prices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reference data everything else joins against, and the daily price history every return is computed from:
- Company names, SIC codes, sectors, current and dated tickers, shares outstanding, and SEC acceptance timestamps for every bulk-loaded filing.
- Daily prices (raw and adjusted) since 2016 for every traded ticker plus the benchmarks.

**Architecture:** Loaders read SEC reference files (`submissions.zip`, `company_tickers_exchange.json`, XBRL frames) into `issuers`, `ticker_evidence`/`tickers` and `filing_acceptance`. Two price providers (Alpaca and yfinance) sit behind the foundation's `PriceProvider` protocol, and one loader fills `prices_daily` incrementally.

**Tech Stack:** Python 3.13, httpx (mocked), pandas 3, yfinance 1.7, SQLAlchemy 2.1.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, sections 6, 7.4, 7.7, 7.8 and 16 (risk: the `acceptanceDateTime` format).

## Global Constraints

Everything in `00-overview.md` › Global Constraints. On top of that:
- Work on branch `ws/c-reference` in your own worktree. Your stubs are `reference/jobs.py` and `prices/jobs.py`. Only create or modify the files listed here, plus their tests.
- Symbols are canonical dot style (`BRK.B`). yfinance uses the dash style (`BRK-B`), so convert only at the provider boundary.
- Nothing ever invents a price. A missing bar is simply missing.
- **Reference snapshots** (`submissions.zip`, `company_tickers_exchange.json`) keep only their *latest* raw copy, overwritten at the same archive path. They're replaceable downloads, not filings.
- Before starting, run `docker compose up -d db`.

## Review Focus

Overview item 1 (ticker changes) depends on this workstream recording the current tickers as evidence: `test_company_tickers_records_evidence`. The spec's risk about the `acceptanceDateTime` timezone is pinned by `test_acceptance_matches_sgml`.

## Interfaces consumed (from the foundation)

- `SecClient` (`.get` and `.download`), `Priority`, `RawArchive`
- `record_ticker_evidence`, `rebuild_tickers`, `canonical_symbol`
- `Sector`, `SECTOR_ETF`, `BENCHMARK_SYMBOLS`, `TRACKED_FORMS`
- `PriceProvider`, `BAR_COLUMNS`, `get_bars`
- The models `Issuer`, `FilingAcceptance`, `PriceDaily`, `Security`, `FundPosition`, `FundManager`, `InsiderTransaction`
- `register_job`, `JobContext`, the fixtures and the factories

## Interfaces produced

- `signals.reference.sectors`: `sector_for_sic(sic: int | None) -> Sector | None` and `assign_sectors(session, issuer_ciks=None) -> int`
- `signals.reference.companies`: `SubmissionFiling`, `SubmissionsRecord`, `parse_submissions_json`, `parse_submissions_page`, `parse_acceptance_datetime`, `load_submissions_zip`, `SubmissionsResult`, `load_company_tickers_exchange`
- `signals.reference.shares`: `frames_url` and `load_shares_frames`
- `signals.prices.alpaca`: `AlpacaProvider` and `FeedNotPermitted`
- `signals.prices.yfinance_provider`: `YFinanceProvider`
- `signals.prices.universe`: `UniverseEntry` and `build_price_universe`
- `signals.prices.loader`: `LoadPricesResult`, `make_providers` and `load_prices`
- Jobs: `backfill_reference`, `reference_refresh`, `tickers_refresh`, `backfill_prices`, `prices_daily`

---

### Task C1: SIC to sector mapping

**Files:**
- Create: `backend/src/signals/reference/sectors.py`, `backend/src/signals/reference/sic_sectors.csv`
- Test: `backend/tests/unit/test_sectors.py`

**Interfaces:**
- **CSV** columns are `sic_from,sic_to,sector`, where an empty `sector` means "no sector". Rows are checked top to bottom and the first match wins, so put specific exceptions before broad ranges.
- `sector_for_sic(sic: int | None) -> Sector | None`, with the mapping cached.
- `assign_sectors(session, issuer_ciks: Collection[int] | None = None) -> int` sets `issuers.sector` from `sic`.

- [ ] **Step 1: Write the failing tests:**

```python
CASES = {3674: "Technology", 3571: "Technology", 3577: "Technology", 7372: "Technology", 3661: "Technology",
  2834: "Health Care", 2836: "Health Care", 3841: "Health Care", 8062: "Health Care", 8071: "Health Care",
  6022: "Financials", 6211: "Financials", 6311: "Financials", 6798: "Real Estate", 6512: "Real Estate",
  1311: "Energy", 2911: "Energy", 1381: "Energy", 4922: "Energy",
  4911: "Utilities", 4931: "Utilities", 4941: "Utilities",
  4813: "Communication Services", 4841: "Communication Services", 7812: "Communication Services",
  2711: "Communication Services",
  5812: "Consumer Discretionary", 3711: "Consumer Discretionary", 5961: "Consumer Discretionary",
  7011: "Consumer Discretionary",
  2080: "Consumer Staples", 2000: "Consumer Staples", 5411: "Consumer Staples", 2111: "Consumer Staples",
  2844: "Consumer Staples",
  3721: "Industrials", 4512: "Industrials", 3531: "Industrials", 4011: "Industrials", 8711: "Industrials",
  1040: "Materials", 2821: "Materials", 2800: "Materials", 3312: "Materials", 1400: "Materials"}

@pytest.mark.parametrize("sic,sector", CASES.items())
def test_sector_for_sic(sic, sector):
    assert sector_for_sic(sic) == Sector(sector)

@pytest.mark.parametrize("sic", [6770, 9995, None])
def test_no_sector(sic):
    assert sector_for_sic(sic) is None

def test_assign_sectors(session):
    make_issuer(session, cik=1000009, sic=2834, sector=None)
    assert assign_sectors(session, [1000009]) == 1
    assert session.get(Issuer, 1000009).sector == "Health Care"
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_sectors.py`. Expected: FAIL.

- [ ] **Step 3:** Write the CSV to cover all 4-digit SIC ranges, then implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(reference): SIC to sector mapping`.

---

### Task C2: `submissions.zip` loader and acceptance timestamps

**Files:**
- Create: `backend/src/signals/reference/companies.py`
- Test: `backend/tests/integration/test_submissions.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class SubmissionFiling: accession_no: str; form: str; filing_date: date; acceptance: datetime | None
@dataclass(frozen=True)
class SubmissionsRecord:
    cik: int; name: str; entity_type: str | None; sic: int | None; sic_description: str | None
    tickers: tuple[str, ...]; exchanges: tuple[str, ...]; state_of_inc: str | None; fiscal_year_end: str | None
    filings: tuple[SubmissionFiling, ...]
@dataclass(frozen=True)
class SubmissionsResult: entities: int; issuers: int; acceptances: int

def parse_acceptance_datetime(raw: str) -> datetime        # tz-aware
def parse_submissions_json(data: bytes) -> SubmissionsRecord      # main file: filings.recent column arrays
def parse_submissions_page(data: bytes) -> tuple[SubmissionFiling, ...]   # overflow file: top-level column arrays
def load_submissions_zip(session, zip_path: Path, *, forms: frozenset[str] = TRACKED_FORMS,
                         batch_size: int = 5000) -> SubmissionsResult
```

**How `load_submissions_zip` works:**
- It streams ZIP members one at a time. `CIK##########.json` members are main files, and `CIK##########-submissions-###.json` members are overflow pages. It never extracts the whole archive.
- It upserts `issuers` only for entities with a SIC code or at least one ticker. It sets name, SIC, SIC description, the first exchange, state of incorporation and fiscal year end, and records each ticker through `record_ticker_evidence(session, cik, t, date.today(), "submissions")`.
- For filings whose form is in `forms`, it inserts `filing_acceptance(accession_no, cik, form_type, filing_date, accepted_at)` with `ON CONFLICT DO NOTHING`. A filing appears under several CIKs, so duplicates are expected.
- It commits every `batch_size` members and runs `rebuild_tickers` for the touched issuers at the end.

- [ ] **Step 1: Write the failing tests:**

```python
def test_acceptance_matches_sgml(fixture_bytes, manifest):
    exp = manifest["submissions_owner"]["expect"]
    sgml = SgmlFiling.from_txt(fixture_bytes("form4_buy_single"))
    assert parse_acceptance_datetime(exp["acceptanceDateTime"]) == sgml.accepted_at

def test_parse_main_file(fixture_bytes, manifest):
    rec = parse_submissions_json(fixture_bytes("submissions_owner"))
    accs = {f.accession_no for f in rec.filings}
    assert manifest["submissions_owner"]["expect"]["accession"] in accs

def test_load_zip_builds_acceptance_and_issuers(session, tmp_path, fixture_bytes, manifest):
    z = tmp_path / "submissions.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(f"CIK{manifest['submissions_owner']['cik']:010d}.json", fixture_bytes("submissions_owner"))
        zf.writestr("CIK0001000001.json", json.dumps({"cik": "1000001", "name": "Acme Corp", "sic": "3571",
            "sicDescription": "Electronic Computers", "tickers": ["ACME"], "exchanges": ["Nasdaq"],
            "filings": {"recent": {"accessionNumber": [], "form": [], "filingDate": [], "acceptanceDateTime": []},
                        "files": []}}))
    res = load_submissions_zip(session, z)
    assert res.issuers == 1 and session.get(Issuer, 1000001).sic == 3571
    acc = manifest["submissions_owner"]["expect"]["accession"]
    assert session.get(FilingAcceptance, acc) is not None
    assert load_submissions_zip(session, z).acceptances == 0          # idempotent
```

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_submissions.py`. Expected: FAIL.

- [ ] **Step 3:** Implement. For `parse_acceptance_datetime`, make `test_acceptance_matches_sgml` pass. The SGML header value (Eastern time) is the truth. If the JSON's trailing `Z` doesn't really mean UTC, treat the wall-clock time as ET, and write down the finding in the function's docstring in one line.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(reference): submissions.zip loader with acceptance timestamps`.

---

### Task C3: Current tickers and shares outstanding

**Files:**
- Create: `backend/src/signals/reference/shares.py`, and add `load_company_tickers_exchange` to `backend/src/signals/reference/companies.py`
- Test: `backend/tests/integration/test_tickers_shares.py`

**Interfaces:**
- `load_company_tickers_exchange(session, data: bytes, *, seen_on: date) -> int`. The JSON has `{"fields": ["cik","name","ticker","exchange"], "data": [[…], …]}`. For each row it upserts the issuer (the name only when the issuer is new, plus the exchange) and calls `record_ticker_evidence(session, cik, ticker, seen_on, "company_tickers")`. Then it runs `rebuild_tickers` for the touched issuers and returns the row count.
- `frames_url(year: int, quarter: int) -> str` returns `https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{year}Q{quarter}I.json`.
- `load_shares_frames(session, data: bytes) -> int`: for each `data[]` item, it sets `issuers.shares_outstanding = val` and `shares_outstanding_as_of = end`, but only for known issuers whose current `as_of` is null or older. Returns the number of rows updated.

- [ ] **Step 1: Write the failing tests:**
  - `test_company_tickers_records_evidence`: load the fixture. The count equals the manifest `n_entries`, and for one fixture issuer `current_symbol(session, cik)` equals the fixture ticker (canonical).
  - `test_frames_update_and_no_downgrade`: seed the `sample` issuer and load the frames fixture, so `shares_outstanding == sample.val`. Then load a hand-built frame with an older `end` and a different value; the value is unchanged.
  - `test_frames_url`: `frames_url(2024, 2).endswith("/CY2024Q2I.json")`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(reference): current tickers and shares outstanding`.

---

### Task C4: Alpaca price provider

**Files:**
- Create: `backend/src/signals/prices/alpaca.py`
- Test: `backend/tests/unit/test_alpaca_provider.py`

**Interfaces:**

```python
class FeedNotPermitted(Exception): ...
class AlpacaProvider:
    name = "alpaca"
    def __init__(self, http: httpx.Client, key_id: str, secret: str, *, feed: str = "sip",
                 base_url: str = "https://data.alpaca.markets", symbols_per_request: int = 100,
                 min_interval_s: float = 0.31, sleep=time.sleep, clock=time.monotonic): ...
    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame
```

**The request:** `GET {base_url}/v2/stocks/bars` with params:
- `symbols` (comma-joined)
- `timeframe=1Day`
- `start=f"{start}T00:00:00Z"` and `end=f"{end}T23:59:59Z"`
- `limit=10000`, `adjustment` (`raw` or `all`), `feed`, `sort=asc`
- `page_token` when paginating

Headers are `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`. It follows `next_page_token` until the token is null, and sleeps so requests are at least `min_interval_s` apart.

**Combining the results:** it makes two passes per batch (`adjustment=raw` and `adjustment=all`). The output columns are `symbol, date, open, high, low, close, volume` from the raw pass and `adj_close` from the adjusted pass's `c`. Each bar's date is its `t` converted to ET.

**Errors:**
- A 403 whose body mentions "subscription" raises `FeedNotPermitted`.
- A 429 sleeps 60 s and retries, up to 5 times.
- A 400 or 422 for a batch of more than one symbol splits the batch in half recursively to isolate bad symbols. Single bad symbols are skipped and returned in `df.attrs["skipped"]`.

- [ ] **Step 1: Write the failing tests** (the MockRouter route is a callable that picks the recorded page from `adjustment` and `page_token`):
  - `test_paginates_and_merges`: for SPY and AAPL, the bar counts equal the manifest `n_bars`, the first date is `2016-01-04`, and `adj_close` equals the `all` fixture close for the same symbol and date.
  - `test_headers_and_params`: the first request has the `APCA-API-KEY-ID` header, `feed=sip` and `timeframe=1Day`.
  - `test_feed_not_permitted`: a 403 with body `{"message":"subscription does not permit querying recent SIP data"}` raises `FeedNotPermitted`.
  - `test_bad_symbol_isolated`: a request containing `BAD` returns 422, and others return the recorded data. The result has no `BAD`, and `df.attrs["skipped"] == ["BAD"]`.

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_alpaca_provider.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(prices): Alpaca daily bars provider (raw and adjusted)`.

---

### Task C5: yfinance price provider

**Files:**
- Create: `backend/src/signals/prices/yfinance_provider.py`
- Test: `backend/tests/unit/test_yfinance_provider.py`

**Interfaces:**

```python
class YFinanceProvider:
    name = "yfinance"
    def __init__(self, download: Callable[..., pd.DataFrame] | None = None, *, batch: int = 50,
                 pause_s: float = 1.0, sleep=time.sleep): ...
    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame
```

- It calls `download(tickers=" ".join(yahoo), start=start, end=end + timedelta(days=1), auto_adjust=False, actions=False, group_by="ticker", threads=False, progress=False)`. `download` defaults to `yfinance.download`, and the Yahoo symbols are canonical ones with `.` replaced by `-`.
- It maps back to canonical symbols. Columns come from `Open`, `High`, `Low`, `Close`, `Volume` and `Adj Close`. Rows with a NaN close are dropped.
- It sleeps `pause_s` between batches.

- [ ] **Step 1: Write the failing tests** using a fake `download` that builds a MultiIndex DataFrame for `BRK-B` and `AAPL`, with one NaN row:
  - The output symbols are `{"BRK.B", "AAPL"}`.
  - The NaN row is dropped.
  - `adj_close` comes from `Adj Close`.
  - The fake received `end = end + 1 day`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(prices): yfinance fallback provider`.

---

### Task C6: Price universe and loader

**Files:**
- Create: `backend/src/signals/prices/universe.py`, `backend/src/signals/prices/loader.py`
- Test: `backend/tests/integration/test_price_loader.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class UniverseEntry: symbol: str; start: date
@dataclass(frozen=True)
class LoadPricesResult: requested: int; loaded: int; rows: int; missing: tuple[str, ...]; fallback_used: tuple[str, ...]

def build_price_universe(session, *, backfill_start: date) -> list[UniverseEntry]
def make_providers(settings: Settings, http: httpx.Client | None = None) -> tuple[PriceProvider, PriceProvider | None]
def load_prices(session_factory, primary: PriceProvider, fallback: PriceProvider | None,
                universe: Sequence[UniverseEntry], *, end: date) -> LoadPricesResult
```

**`build_price_universe`** is the union, deduplicated by symbol with the minimum start, of:
1. Every `tickers` interval of each issuer that has an `insider_transactions` row with `transaction_date >= backfill_start`, where the interval overlaps `[backfill_start, today]`. Start = `max(backfill_start - 120 days, valid_from)`.
2. `securities.ticker` for the CUSIPs held (effective positions) by funds with `is_tracked`. Start = `backfill_start - 120 days`.
3. `BENCHMARK_SYMBOLS`. Start = `backfill_start - 120 days`.

**`make_providers`:** when `price_primary == "alpaca"` and a key and secret exist, it returns `(AlpacaProvider(...), YFinanceProvider())`. Otherwise it returns `(YFinanceProvider(), None)`.

**`load_prices`:**
- Each symbol's effective start is `max(entry.start, last stored date + 1)`. Symbols whose start is after `end` are skipped.
- Symbols sharing the same start are batched to the primary. Rows are upserted with `source = provider.name`, one commit per batch.
- Symbols with zero rows from the primary go to the fallback. If the fallback also returns nothing, they're reported in `missing`.

- [ ] **Step 1: Write the failing tests** (fake providers record their calls):
  - `test_universe_includes_benchmarks_and_both_tickers`:
    - Seed an issuer with evidence `GBX` (2016) and `GLBX` (2022), and one P transaction in 2023.
    - The universe symbols include `GBX`, `GLBX`, `SPY`, `QQQ`, `XLK` and every other `SECTOR_ETF` value.
  - `test_incremental_start`: seed `make_prices(session, "ACME", date(2024,1,2), [1]*7)`, which runs through 2024-01-10. The primary is called for `ACME` with start `date(2024,1,11)`.
  - `test_fallback_and_missing`: the primary returns nothing for `OLD` or `GONE`. The fallback returns rows for `OLD`, so `fallback_used == ("OLD",)` and `missing == ("GONE",)`, and `OLD`'s rows have `source == "fake_fallback"`.
  - `test_idempotent`: a second run with the same `end` inserts 0 rows.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_price_loader.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(prices): price universe and incremental loader with fallback`.

---

### Task C7: Jobs

**Files:**
- Modify: `backend/src/signals/reference/jobs.py`, `backend/src/signals/prices/jobs.py` (your stubs)
- Test: `backend/tests/integration/test_jobs_reference_prices.py`

**Interfaces** (each registered through `@register_job`):
- **`backfill_reference`** (on request), resumable:
  1. `ctx.sec.download("https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip", settings.raw_archive_dir / "reference" / "submissions.zip")`, then `load_submissions_zip`.
  2. `company_tickers_exchange.json` from `https://www.sec.gov/files/company_tickers_exchange.json`, archived as `("reference", "company_tickers_exchange", "json")`, then loaded.
  3. Frames from 2016Q1 through the last completed quarter, each archived as `("reference", f"frames-CY{y}Q{q}I", "json")`. A 404 for a quarter is skipped.
  4. `assign_sectors`.
- **`reference_refresh`**, `cron={"day_of_week": "sun", "hour": 4, "minute": 0}`: the same steps, but frames only for the last 4 quarters.
- **`tickers_refresh`**, `cron={"hour": 5, "minute": 0}`: step 2 only.
- **`backfill_prices`** (on request): `build_price_universe`, then `load_prices(end=yesterday_et)`. It returns the result as a dict and stores `app_state["prices_last"]`.
- **`prices_daily`**, `cron={"day_of_week": "mon-fri", "hour": 18, "minute": 30}`: the same, with `end = today_et` if today is a trading day, otherwise yesterday.

- [ ] **Step 1: Write the failing tests:**
  - `test_jobs_registered`: the kinds and crons match the list above.
  - `test_backfill_reference_with_mocks`:
    - The MockRouter serves a small ZIP (built as in C2) at the `submissions.zip` URL, the tickers fixture, a 404 for every frame except one, and the frames fixture.
    - After running, issuers exist, `filing_acceptance` has the fixture accession, and the sectors are assigned.
    - Monkeypatch the quarter range to 2 quarters so the test stays quick.
  - `test_prices_daily_uses_providers`: monkeypatch `make_providers` to fakes. Rows are written for the benchmarks.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest -q`. Expected: the whole backend suite passes.

- [ ] **Step 5: Commit** with message `feat(reference,prices): reference and price jobs`.
