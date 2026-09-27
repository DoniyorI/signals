# Workstream B: Fund (13F) and Stake (13D/13G) Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load every 13F holdings report since 2016 (bulk data sets plus live filings) with correct amendment handling and quarter-over-quarter changes, map CUSIPs to tickers, keep the tracked-fund list current, and ingest XML Schedules 13D/13G since 2024-12-18.

**Architecture:** This mirrors workstream A: pure parsers, then normalizers inside the caller's transaction, then handlers registered with the foundation dispatch, then a COPY-based bulk loader, then jobs. `fund_positions` stores one row per filing and CUSIP with `is_effective`, so a restatement only flips flags.

**Tech Stack:** Python 3.13, lxml, SQLAlchemy 2.1, psycopg 3 COPY, httpx (mocked), rapidfuzz.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, sections 6, 7.4–7.7, 9.5 and 9.7.

## Global Constraints

Everything in `00-overview.md` › Global Constraints. On top of that:
- Work on branch `ws/b-funds` in your own worktree. Only create or modify the files listed here, plus their tests.
- Your stubs are `ingest/handlers/funds.py` and `ingest/jobs_funds.py`.
- **13F values:** `value × 1000` when `filed_date < 2023-01-03`, otherwise `value` as-is. Stored as `value_usd`.
- **Percent of class** is stored as a fraction (`7.2` becomes `0.072`).
- Before starting, run `docker compose up -d db`.

## Review Focus

- Overlapping data sets (quarterly versus 3-month files) must not double-count. Test: B5 `test_overlap_dedupes_by_accession`.
- A 13F-HR/A RESTATEMENT must replace, and a NEW HOLDINGS amendment must add. Test: B2 `test_restatement_and_new_holdings`.

## Interfaces consumed (from the foundation)

- `SgmlFiling`, the `xmlutil` helpers, `register_handler`, `ingest_raw`, `Filing`
- The models `FundManager`, `FundFiling`, `FundPosition`, `FundPositionChange`, `Security`, `OwnershipStake`, `Issuer`, `PriceDaily`
- `FeedItemIn`, `upsert_feed_item`, `canonical_symbol`, `issuer_for_symbol`, `current_symbol`, `set_state`
- `register_job`, `JobContext`, `track_run`, and the test fixtures and factories

## Interfaces produced

- `signals.ingest.parsers.form13f`: `F13FCover`, `F13FHolding`, `parse_13f_primary`, `parse_13f_infotable`, `value_to_usd`
- `signals.ingest.parsers.schedule13`: `ReportingPerson`, `Schedule13Doc`, `parse_schedule13`
- `signals.ingest.normalize_funds`: `normalize_13f(session, filing, cover, holdings) -> None`, `refresh_effective(session, filer_cik: int, period: date) -> None`, `fund_summary(period: date, positions: int, value_usd: float) -> str`
- `signals.ingest.normalize_stakes`: `normalize_stake(session, filing, doc) -> None`
- `signals.ingest.fund_changes`: `compute_fund_changes(session, *, filer_ciks=None, periods=None) -> int`, `refresh_fund_manager_stats(session, *, filer_ciks=None) -> int`, `flag_value_unit_anomalies(session, *, periods=None) -> int`
- `signals.ingest.bulk_13f`: `F13FDatasetLink`, `list_13f_datasets`, `load_13f_zip`, `F13FLoadResult`
- `signals.reference.cusip`: `OpenFigiClient`, `FigiMatch`, `choose_listing`, `map_securities`, `MapResult`, `name_match_issuer`
- `signals.reference.tracked_funds`: `CuratedFund`, `load_curated`, `refresh_tracked_funds`
- Jobs: `backfill_funds`, `bulk_check_funds`, `cusip_map`, `fund_changes` (params `filer_ciks`), `tracked_funds_refresh`

---

### Task B1: 13F parsers

**Files:**
- Create: `backend/src/signals/ingest/parsers/form13f.py`, `backend/tests/fixtures/golden/{f13f_small,f13f_pre2023,f13f_restatement}.json`
- Test: `backend/tests/unit/test_parse_13f.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class F13FCover:
    submission_type: str; period_of_report: date; is_amendment: bool; amendment_no: int | None
    amendment_type: Literal["RESTATEMENT", "NEW HOLDINGS"] | None; report_type: str | None
    manager_name: str; other_included_managers: int | None; table_entry_total: int | None
    table_value_total: float | None      # as reported (units depend on filing date)
    is_confidential_omitted: bool | None

@dataclass(frozen=True)
class F13FHolding:
    row_no: int; name_of_issuer: str; title_of_class: str | None; cusip: str; figi: str | None
    value_reported: float; shares: float; sh_prn: Literal["SH", "PRN"]; put_call: Literal["PUT", "CALL"] | None
    investment_discretion: str | None; other_manager: str | None
    voting_sole: float | None; voting_shared: float | None; voting_none: float | None

def parse_13f_primary(xml: bytes) -> F13FCover        # root edgarSubmission; reportCalendarOrQuarter is MM-DD-YYYY
def parse_13f_infotable(xml: bytes) -> list[F13FHolding]   # root informationTable/infoTable (namespace-agnostic)
def value_to_usd(value_reported: float, filed_date: date) -> float
```

- CUSIPs are upper-cased and stripped.
- Normalize `putCall` to upper case.
- An `amendmentType` value of `"NEW HOLDINGS"` is kept verbatim.

- [ ] **Step 1: Write the failing tests:**

```python
def test_value_to_usd_boundary():
    assert value_to_usd(1234, date(2022, 11, 14)) == 1_234_000.0
    assert value_to_usd(1234, date(2023, 1, 3)) == 1234.0

@pytest.mark.parametrize("key", ["f13f_small", "f13f_pre2023", "f13f_restatement"])
def test_matches_golden_and_anchors(key, fixture_bytes, manifest):
    sg = SgmlFiling.from_txt(fixture_bytes(key))
    docs = {d.type: d for d in sg.xml_documents()}
    cover = parse_13f_primary(docs[sg.form_type].xml())
    rows = parse_13f_infotable(docs["INFORMATION TABLE"].xml())
    assert to_jsonable(cover, rows) == json.loads(golden_path(key).read_text())
    exp = manifest[key]["expect"]
    assert str(cover.period_of_report) == exp["period_of_report"] and len(rows) == exp["n_rows"]
    assert sum(r.value_reported for r in rows) == pytest.approx(exp["table_value_total"], rel=1e-6)

def test_restatement_type(fixture_bytes):
    sg = SgmlFiling.from_txt(fixture_bytes("f13f_restatement"))
    cover = parse_13f_primary({d.type: d for d in sg.xml_documents()}[sg.form_type].xml())
    assert cover.amendment_type == "RESTATEMENT" and cover.is_amendment is True
```

  `to_jsonable(cover, rows)` is a helper defined in the parser module.

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_parse_13f.py`. Expected: FAIL.

- [ ] **Step 3:** Implement. Generate the golden files and check them against the sec.gov information table view.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(funds): 13F primary document and information table parsers`.

---

### Task B2: 13F normalizer and effective positions

**Files:**
- Create: `backend/src/signals/ingest/normalize_funds.py`
- Test: `backend/tests/integration/test_normalize_funds.py`

**Interfaces:**
- `normalize_13f(session, filing: Filing, cover: F13FCover, holdings: list[F13FHolding]) -> None`:
  - Upsert `fund_managers(cik=filing.primary_cik, name=cover.manager_name)`.
  - Upsert `fund_filings` with `value_total_usd = value_to_usd(table_value_total, filed_date)`.
  - Replace this accession's `fund_positions`, aggregating duplicate `(cusip, put_call)` rows within the filing: sum `shares` and `value_usd`, keep the first name and title. `put_call` is `''` when absent.
  - Call `refresh_effective`.
  - Upsert the feed item: `direction="other"`, `codes=[filing.form_type]`, `owner_ciks=[filer]`, `summary=fund_summary(...)`.
  - A 13F-NT writes `fund_filings` only, with summary `"13F notice (holdings reported by another manager)"`.
- `refresh_effective(session, filer_cik, period)`:
  - Among that filer and period's non-NT `fund_filings`, ordered by `(accepted_at NULLS LAST, filed_date, accession_no)`:
    - The **base** is the latest filing whose `amendment_type` is `None` or `RESTATEMENT`.
    - The effective set is the base plus every `NEW HOLDINGS` filing ordered after it.
  - Set `fund_positions.is_effective` and `fund_filings.superseded` (true when not effective).
- `fund_summary(period, positions, value_usd) -> str` returns `f"13F for Q{q} {year}: {positions} positions, {short}"`, where `short` is `$X.XB` at or above 1e9, `$X.XM` at or above 1e6, `$XK` at or above 1e3, and otherwise `$X`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_small_13f_positions(session, manifest):
    acc = load(session, "f13f_small")                       # ingest_raw with a local handler
    n = session.scalar(select(func.count()).select_from(FundPosition).where(FundPosition.accession_no == acc))
    assert 0 < n <= manifest["f13f_small"]["expect"]["n_rows"]

def test_pre2023_values_scaled(session, manifest):
    acc = load(session, "f13f_pre2023"); first = manifest["f13f_pre2023"]["expect"]["first_row"]
    v = session.scalar(select(func.sum(FundPosition.value_usd)).where(FundPosition.accession_no == acc,
                                                                      FundPosition.cusip == first["cusip"]))
    assert v >= first["value_reported"] * 1000

def test_restatement_and_new_holdings(session):
    make_fund_manager(session)
    orig = make_fund_filing(session, accession_no="0003000001-24-000001", filed_date=date(2024, 5, 15))
    make_fund_position(session, accession_no=orig.accession_no, cusip="000000AA1")
    rest = make_fund_filing(session, accession_no="0003000001-24-000002", filed_date=date(2024, 6, 1),
                            submission_type="13F-HR/A", amendment_type="RESTATEMENT")
    make_fund_position(session, accession_no=rest.accession_no, cusip="000000BB2")
    add = make_fund_filing(session, accession_no="0003000001-24-000003", filed_date=date(2024, 6, 10),
                           submission_type="13F-HR/A", amendment_type="NEW HOLDINGS")
    make_fund_position(session, accession_no=add.accession_no, cusip="000000CC3")
    refresh_effective(session, 3000001, date(2024, 3, 31))
    eff = set(session.scalars(select(FundPosition.cusip).where(FundPosition.is_effective)))
    assert eff == {"000000BB2", "000000CC3"}

def test_fund_summary():
    assert fund_summary(date(2026, 6, 30), 45, 268_100_000_000) == "13F for Q2 2026: 45 positions, $268.1B"
    assert fund_summary(date(2024, 3, 31), 3, 950) == "13F for Q1 2024: 3 positions, $950"
```

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_normalize_funds.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(funds): normalize 13F filings with effective-position amendments`.

---

### Task B3: Quarter-over-quarter changes, manager stats, unit sanity check

**Files:**
- Create: `backend/src/signals/ingest/fund_changes.py`
- Test: `backend/tests/integration/test_fund_changes.py`

**Interfaces:**
- `compute_fund_changes(session, *, filer_ciks: Collection[int] | None = None, periods: Collection[date] | None = None) -> int`: SQL over effective positions aggregated by `(filer, period, cusip, put_call)`.
  - "Previous" means the filer's greatest period below the current one that has effective positions.
  - `change` values: `NEW` (none before), `EXIT` (present before, absent now: written with `shares=0` and `value_usd=0`), `ADD` (now > prev), `TRIM` (now < prev), `SAME`.
  - `shares_change_pct = (now - prev) / prev` when prev > 0.
  - `weight = value / Σ value` over the period's `put_call=''` rows. Option rows get weight NULL. `prev_weight` is the same measure for the previous period.
  - It replaces rows for the touched `(filer, period)` keys.
- `refresh_fund_manager_stats(session, *, filer_ciks=None) -> int` sets `latest_period`, `latest_value_usd` (the sum of effective values) and `latest_positions` (the count of effective `put_call=''` rows).
- `flag_value_unit_anomalies(session, *, periods=None) -> int`:
  - For effective positions whose CUSIP maps to a ticker with a close on the period date, it computes `implied = value_usd / shares`.
  - It flags a position when `implied / close > 100` or `< 0.01`.
  - It writes `app_state["f13f_unit_anomalies"] = {"count": n, "sample": [up to 20 {accession, cusip, implied, close}]}` and returns `n`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_changes_new_add_same_exit(session):
    make_fund_manager(session)
    q1 = make_fund_filing(session, accession_no="0003000001-24-000001", period=date(2024, 3, 31))
    q2 = make_fund_filing(session, accession_no="0003000001-24-000002", period=date(2024, 6, 30),
                          filed_date=date(2024, 8, 14))
    for cusip, sh in [("000000AA1", 100), ("000000BB2", 50), ("000000CC3", 10)]:
        make_fund_position(session, accession_no=q1.accession_no, period=date(2024, 3, 31), cusip=cusip,
                           shares=sh, value_usd=sh * 10.0)
    for cusip, sh in [("000000AA1", 150), ("000000BB2", 50), ("000000DD4", 20)]:
        make_fund_position(session, accession_no=q2.accession_no, period=date(2024, 6, 30), cusip=cusip,
                           shares=sh, value_usd=sh * 10.0)
    compute_fund_changes(session, filer_ciks=[3000001])
    rows = {r.cusip: r for r in session.scalars(select(FundPositionChange).where(
        FundPositionChange.period == date(2024, 6, 30)))}
    assert (rows["000000AA1"].change, rows["000000AA1"].shares_change_pct) == ("ADD", 0.5)
    assert rows["000000BB2"].change == "SAME"
    assert rows["000000CC3"].change == "EXIT" and rows["000000CC3"].shares == 0
    assert rows["000000DD4"].change == "NEW"
    assert rows["000000AA1"].weight == pytest.approx(1500 / 2200)

def test_manager_stats(session):
    seed_two_quarters(session)            # the same rows as test_changes_new_add_same_exit (a shared helper)
    assert refresh_fund_manager_stats(session, filer_ciks=[3000001]) == 1
    m = session.get(FundManager, 3000001)
    assert (m.latest_period, m.latest_value_usd, m.latest_positions) == (date(2024, 6, 30), 2200.0, 3)

def test_unit_anomaly_flagged(session):
    make_issuer(session); make_security(session, cusip="000000AA1", ticker="ACME")
    make_prices(session, "ACME", date(2024, 3, 28), [10.0])
    make_fund_manager(session); f = make_fund_filing(session, period=date(2024, 3, 28))
    make_fund_position(session, accession_no=f.accession_no, period=date(2024, 3, 28), cusip="000000AA1",
                       shares=100, value_usd=1_000_000)
    assert flag_value_unit_anomalies(session) == 1
```

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_fund_changes.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(funds): quarter-over-quarter changes, manager stats, unit sanity check`.

---

### Task B4: Schedule 13D/13G parser and normalizer

**Files:**
- Create: `backend/src/signals/ingest/parsers/schedule13.py`, `backend/src/signals/ingest/normalize_stakes.py`, `backend/tests/fixtures/golden/{sc13d,sc13g}.json`
- Test: `backend/tests/unit/test_parse_schedule13.py`, `backend/tests/integration/test_normalize_stakes.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ReportingPerson:
    name: str; cik: int | None; sole_voting: float | None; shared_voting: float | None
    sole_dispositive: float | None; shared_dispositive: float | None; aggregate_owned: float | None
    percent_of_class: float | None      # fraction
    type_of_reporting_person: str | None

@dataclass(frozen=True)
class Schedule13Doc:
    form_type: str; issuer_cik: int | None; issuer_name: str | None; cusip: str | None
    event_date: date | None; amendment_no: int | None; persons: tuple[ReportingPerson, ...]
    purpose: str | None                 # 13D Item 4, truncated to 4000 chars

def parse_schedule13(xml: bytes, form_type: str) -> Schedule13Doc
def normalize_stake(session, filing: Filing, doc: Schedule13Doc) -> None
```

**What `normalize_stake` writes:**
- `ownership_stakes`:
  - `is_activist = form_type.startswith("SCHEDULE 13D")`.
  - `percent_of_class` and `shares` come from the person with the maximum `percent_of_class`.
  - `group_key = "|".join(sorted(str(p.cik) if p.cik else p.name.upper() for p in persons))`.
  - `reporting_persons` holds the JSON list.
- `is_current`: within `(group_key, issuer_cik)`, only the newest row by `(event_date, accepted_at, accession_no)` is true.
- The feed item: `summary = f"{'13D' if activist else '13G'}: {pct:.1%} of class"`, or `"13D filed"` when the percent is unknown, with `codes=[form_type]`.

Element paths come from the recorded fixtures and the SEC Schedule 13D/13G XML technical specifications. The golden files pin them.

- [ ] **Step 1: Write the failing tests.**
  - The golden-file match for `sc13d` and `sc13g`.
  - Anchors: `issuer_cik`, `cusip`, `len(persons) == n_persons`, and `max(percent) == pytest.approx(max_percent_of_class / 100)`.
  - `test_is_current_flips`: normalize a `sc13g` fixture, then a factory-made newer filing with the same group and issuer. The old one has `is_current False` and the new one `True`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(stakes): Schedule 13D/13G parser and normalizer`.

---

### Task B5: Bulk loader for the Form 13F Data Sets

**Files:**
- Create: `backend/src/signals/ingest/bulk_13f.py`
- Test: `backend/tests/integration/test_bulk_13f.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class F13FDatasetLink: name: str; url: str; start: date; end: date
@dataclass(frozen=True)
class F13FLoadResult: accessions: int; skipped_existing: int; positions: int

def list_13f_datasets(html: str, base_url: str = "https://www.sec.gov") -> list[F13FDatasetLink]
def load_13f_zip(session, zip_bytes: bytes) -> F13FLoadResult
```

- `list_13f_datasets` matches `(\d{4})q([1-4])_form13f\.zip`, where start and end are that calendar quarter's first and last days. It also matches `(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})_form13f\.zip`, such as `01jun2026-31aug2026`. The result is sorted by `start`.
- `load_13f_zip` uses the same COPY method as A10: CSV format, `QUOTE E'\x01'`, errors replaced, TEMP tables for SUBMISSION, COVERPAGE, SUMMARYPAGE and INFOTABLE.
  - Accessions already in `fund_filings` are skipped.
  - It writes `filings` (`source='bulk_13f'`, `parse_status='parsed'`, `accepted_at` from `filing_acceptance` when present), `fund_managers`, `fund_filings` and `fund_positions`.
  - `fund_positions` is aggregated per `(accession, cusip, put_call)`, with `value_usd = VALUE * CASE WHEN filing_date < '2023-01-03' THEN 1000 ELSE 1 END`.
  - Then it runs `refresh_effective` for every touched `(filer, period)` and builds the feed items in Python batches.

- [ ] **Step 1: Write the failing tests:**
  - `test_list_both_naming_styles`: the count equals the manifest `n_links`. `2013q2_form13f.zip` is present with start `2013-04-01`. `01jun2026-31aug2026_form13f.zip` has start `2026-06-01` and end `2026-08-31`.
  - `test_load_2022_slice_scales_thousands`: for the `sample` accession and CUSIP, `value_usd == value_reported * 1000`.
  - `test_load_2025_slice_dollars`: for the `sample`, `value_usd == value_reported`.
  - `test_overlap_dedupes_by_accession`: loading `bulk_13f_slice_2025` twice gives `skipped_existing == len(accessions)` the second time, and the position count is unchanged.
  - `test_restatement_in_slice_marks_superseded`: the `restatement_accession`'s earlier sibling (same filer and period, if present in the slice) is `superseded` and its positions aren't effective. If no sibling is in the slice, assert the restatement rows are effective.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_bulk_13f.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(funds): bulk loader for SEC Form 13F Data Sets`.

---

### Task B6: CUSIP to ticker mapping

**Files:**
- Create: `backend/src/signals/reference/cusip.py`
- Test: `backend/tests/integration/test_cusip_map.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FigiMatch: ticker: str; exch_code: str; figi: str; security_type: str | None; name: str | None; market_sector: str | None
@dataclass(frozen=True)
class MapResult: requested: int; mapped_openfigi: int; mapped_name: int; unresolved: int

class OpenFigiClient:
    def __init__(self, http: httpx.Client, api_key: str | None, *, sleep=time.sleep, clock=time.monotonic): ...
    def map_cusips(self, cusips: Sequence[str]) -> dict[str, FigiMatch | None]
def choose_listing(candidates: list[dict]) -> FigiMatch | None
def name_match_issuer(session, name_of_issuer: str) -> int | None
def map_securities(session, figi: OpenFigiClient, *, limit: int | None = None) -> MapResult
```

**`OpenFigiClient`:**
- POSTs to `https://api.openfigi.com/v3/mapping` with the body `[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"}, …]` and the header `X-OPENFIGI-APIKEY` when a key is set.
- Batches: 100 jobs per request with a key, 10 without.
- Minimum spacing between requests: 0.24 s with a key, 2.4 s without.
- A 429 sleeps `int(resp.headers.get("ratelimit-reset", "60"))` and retries, up to 5 times.
- Each response item is `{"data": [...]}` or `{"warning": ...}`. A warning maps to `None`.

**`choose_listing`:** prefers `marketSector == "Equity"`, then `exchCode == "US"`, and returns the first match. The ticker goes through `canonical_symbol`.

**`name_match_issuer`:**
- Both names are normalized: upper case, punctuation removed, and these tokens dropped: `INC INCORPORATED CORP CORPORATION CO COMPANY LTD LIMITED PLC LLC LP HOLDINGS HLDGS GROUP THE NEW CL CLASS COM SA NV AG`.
- Candidates are issuers whose normalized name shares the first token (SQL `ILIKE 'TOKEN%'`).
- The best `rapidfuzz.fuzz.token_sort_ratio` wins if it's at least 92.

**`map_securities`:**
- Takes distinct effective `fund_positions.cusip` values that have no `securities` row, or whose `map_status='pending'`.
- OpenFIGI matches become `securities(ticker, figi, security_type, name, issuer_cik=issuer_for_symbol(ticker), map_source='openfigi', map_status='mapped')`.
- Otherwise it tries `name_match_issuer` with the position's `name_of_issuer`, producing `map_source='name_match'` and `ticker=current_symbol(issuer)`.
- Otherwise the row is `map_source='none'`, `map_status='unresolved'`.

- [ ] **Step 1: Write the failing tests:**
  - `test_openfigi_fixture`: a MockRouter POST returns `openfigi_sample`. `037833100` maps to `AAPL`, and `000000000` maps to `None`.
  - `test_batches_without_key`: 25 CUSIPs cause 3 POSTs, with sleeps between them of at least 2.4 s on the fake clock.
  - `test_429_retry`: the first response is 429 with `ratelimit-reset: 7`, so the client sleeps 7 and then succeeds.
  - `test_choose_listing_prefers_equity_us`.
  - `test_name_match`: seed issuer `Acme Corp` (1000001). `name_match_issuer(session, "ACME CORP COM") == 1000001`, and `name_match_issuer(session, "ACMEX LTD")` returns `None`.
  - `test_map_securities_end_to_end`: seed positions for two CUSIPs. The router maps one; the other is resolved by name match. The result is `MapResult(requested=2, mapped_openfigi=1, mapped_name=1, unresolved=0)`.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_cusip_map.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(funds): CUSIP to ticker mapping via OpenFIGI with name-match fallback`.

---

### Task B7: Tracked funds

**Files:**
- Create: `backend/src/signals/reference/tracked_funds.py`
- Test: `backend/tests/integration/test_tracked_funds.py`

**Interfaces:**
- `CuratedFund(cik: int, name: str, reason: str)`
- `load_curated(path: Path = <package>/reference/tracked_funds.csv) -> list[CuratedFund]`
- `refresh_tracked_funds(session, *, curated: list[CuratedFund], top_n: int, max_positions: int) -> int`:
  1. Call `refresh_fund_manager_stats`.
  2. Set `is_tracked=false` everywhere.
  3. Mark the curated CIKs that exist as tracked, with `tracked_reason='curated'`.
  4. Mark the top `top_n` by `latest_value_usd` among the rest with `latest_positions <= max_positions`, with `tracked_reason='top_active'`.
  5. Return the tracked count.

- [ ] **Step 1: Write the failing tests.** `test_curated_plus_top_active`: seed 5 managers with values `[5e9, 4e9, 3e9, 2e9, 1e9]` and positions `[500, 20, 30, 40, 10]`. Curated is `[the 1e9 one]`, `top_n=2` and `max_positions=100`. The tracked set is the curated one plus the 4e9 and 3e9 managers, and the function returns 3. Also `test_load_curated_csv`: at least 40 rows, all with integer CIKs.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(funds): tracked fund selection (curated plus top active)`.

---

### Task B8: Handlers and jobs

**Files:**
- Modify: `backend/src/signals/ingest/handlers/funds.py`, `backend/src/signals/ingest/jobs_funds.py` (your stubs)
- Test: `backend/tests/integration/test_handlers_funds.py`, `backend/tests/integration/test_jobs_funds.py`

**Interfaces:**
- `handle_13f(session, sgml, filing, ctx)`: the XML document whose root is `edgarSubmission` is the cover, and the one whose root is `informationTable` holds the holdings (absent for NT). It calls `normalize_13f`.
- `handle_schedule13(session, sgml, filing, ctx)`: the first XML document, then `parse_schedule13(xml, sgml.form_type)`, then `normalize_stake`.
- Registration at import: `register_handler(FUND_FORMS, handle_13f)` and `register_handler(STAKE_FORMS, handle_schedule13)`.
- **Jobs:**
  - **`backfill_funds`** (on request), resumable through `ctx.progress`:
    1. Fetch the listing `https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets`.
    2. For each dataset with `end >= settings.backfill_start` not in `progress["datasets_done"]`: fetch it (archived as `("bulk", name, "zip")`), run `load_13f_zip`, and commit.
    3. `_apply_acceptance(ctx)`.
    4. `_gap_fill(ctx, FUND_FORMS, start=<day after last dataset end>)`.
    5. `_gap_fill(ctx, STAKE_FORMS, start=settings.stakes_start)`.
    6. `compute_fund_changes`, then `map_securities`, then `flag_value_unit_anomalies`, then `refresh_tracked_funds`.

    `_apply_acceptance` and `_gap_fill` are module-level wrappers that import `signals.ingest.bulk_345.apply_acceptance_times` and `signals.ingest.gap_fill.gap_fill` *inside the function* (workstream A provides those). Tests monkeypatch the wrappers.
  - **`bulk_check_funds`**, `cron={"day_of_week": "mon", "hour": 3, "minute": 15}`: loads datasets missing from `app_state["bulk_13f_loaded"]`.
  - **`cusip_map`** (on request): `map_securities`.
  - **`fund_changes`** (on request, params `filer_ciks`): `compute_fund_changes`, then `refresh_fund_manager_stats`.
  - **`tracked_funds_refresh`**, `cron={"day_of_week": "sun", "hour": 5, "minute": 0}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_fixtures_ingest`: `ingest_raw` for `f13f_small`, `f13f_pre2023`, `f13f_restatement`, `sc13d` and `sc13g` all give status `parsed`.
  - `test_jobs_registered`: those kinds exist with the crons above.
  - `test_backfill_funds_resumes`: a MockRouter serves the listing and slice ZIPs, with the wrappers monkeypatched to no-ops. Only datasets not in `datasets_done` are requested, and the steps run in the listed order (record the calls).

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest -q`. Expected: the whole backend suite passes.

- [ ] **Step 5: Commit** with message `feat(funds): 13F and 13D/G handlers and fund jobs`.
