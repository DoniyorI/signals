# Workstream A: Insider Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get every Form 3/4/5 and Form 144 into the canonical tables. That covers the live feed, the nightly reconcile, per-filing gap fills and the bulk data sets since 2016, with amendments and joint filings handled correctly.

**Architecture:**
- Pure parsers turn XML bytes into dataclasses.
- Normalizers write the canonical rows inside the caller's transaction.
- The handlers registered with the foundation's dispatch registry connect them to `ingest_raw`.
- The feed, index and bulk modules decide *which* accessions to ingest.
- The jobs module schedules all of it.

**Tech Stack:** Python 3.13, lxml, SQLAlchemy 2.1, psycopg 3 COPY, httpx (mocked in tests).

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, sections 5.3, 6, 7.1–7.6 and 13.

## Global Constraints

Everything in `00-overview.md` › Global Constraints. On top of that:
- Work on branch `ws/a-insider` in your own worktree.
- Only create or modify the files listed in this plan's tasks, plus their tests.
- Foundation files are read-only, except the stubs `ingest/handlers/insider.py` and `ingest/jobs_insider.py`, which belong to you.
- Before starting, run `docker compose up -d db` from the repo root (Postgres is needed for the integration tests).

## Review Focus

- Overview item 5: a live-feed burst of more than 100 entries. Tests A7 `test_poll_paginates_until_known_accession` and A8 `test_reconcile_ingests_only_missing`.
- A row reporting `valueOwnedFollowingTransaction`, or a footnote-only price, must parse to `None` with footnote ids and must not crash. Tests are in A1.

## Interfaces consumed (from the foundation)

- `signals.sec.sgml.SgmlFiling` and `SgmlDocument.xml()`
- `signals.ingest.parsers.xmlutil`: `parse_xml`, `field`, `text`, `to_bool`, `to_float`, `to_date`, `FieldValue`
- `signals.ingest.dispatch`: `register_handler`, `HandlerContext`
- `signals.ingest.pipeline`: `ingest_accession`, `ingest_raw`, `IngestOutcome`
- `signals.domain.*`: `owner_group_key`, `normalize_roles`, `top_role`, `record_ticker_evidence`, `rebuild_tickers`, `FeedItemIn`, `upsert_feed_item`, `summarize_trade`, `set_state`, `get_state`, the calendar functions, and the constants in `types`
- `signals.sec.client`: `SecClient`, `Priority`, `SecNotFoundError`
- `signals.jobs`: `register_job`, `JobContext`, `track_run`, `request_job`
- ORM models, test fixtures (`session`, `session_factory`, `settings`, `manifest`, `fixture_bytes`, `MockRouter`, `tmp_archive`) and `tests.factories`

## Interfaces produced (other workstreams and integration rely on these exact names)

- `signals.ingest.parsers.ownership`: `parse_ownership(xml: bytes) -> OwnershipDoc`, plus the `OwnershipDoc`, `OwnershipRow` and `ReportingOwner` dataclasses
- `signals.ingest.parsers.form144`: `parse_form144(xml: bytes) -> Form144Doc`
- `signals.ingest.normalize_insider`: `normalize_ownership(session, filing, doc) -> None`
- `signals.ingest.amendments`: `link_amendment(session, amendment_accession: str) -> str | None` and `relink_orphans(session) -> int`
- `signals.ingest.normalize_form144`: `normalize_form144(session, filing, doc, sgml) -> None`
- `signals.ingest.feed`: `FeedEntry`, `parse_atom`, `feed_url`, `poll_feed`, `PollResult`
- `signals.ingest.indexes`: `IndexEntry`, `parse_form_idx`, `daily_index_url`, `full_index_url`, `reconcile_day`, `ReconcileResult`
- `signals.ingest.gap_fill`: `gap_fill(...) -> GapFillResult`. Workstream B calls it for 13F and 13D/G gap fills.
- `signals.ingest.bulk_345`: `DatasetLink`, `list_345_datasets`, `load_345_zip`, `apply_acceptance_times`, `BulkLoadResult`
- Jobs: `live_poll`, `reconcile_daily`, `backfill_insiders`, `bulk_check_insiders`
- Job kinds this workstream *requests* by name: `analytics_incremental` (params `issuer_ciks` and `owner_ciks`) and `fund_changes` (params `filer_ciks`)

---

### Task A1: Ownership (Forms 3/4/5) parser

**Files:**
- Create: `backend/src/signals/ingest/parsers/ownership.py`
- Test: `backend/tests/unit/test_parse_ownership.py`
- Create: `backend/tests/fixtures/golden/<key>.json`, one per ownership fixture

**Interfaces:**

```python
@dataclass(frozen=True)
class ReportingOwner:
    cik: int; name: str; is_director: bool; is_officer: bool; officer_title: str | None
    is_ten_pct_owner: bool; is_other: bool; other_text: str | None

@dataclass(frozen=True)
class OwnershipRow:
    table_kind: Literal["nonderiv", "deriv"]; row_kind: Literal["transaction", "holding"]; row_no: int
    security_title: str | None; transaction_date: date | None; deemed_execution_date: date | None
    code: str | None; form_type: str | None; equity_swap: bool | None; timeliness: str | None
    shares: float | None; price: float | None; acquired_disposed: Literal["A", "D"] | None
    shares_owned_after: float | None; value_owned_after: float | None
    direct_indirect: Literal["D", "I"] | None; nature_of_ownership: str | None
    exercise_price: float | None; exercise_date: date | None; expiration_date: date | None
    underlying_title: str | None; underlying_shares: float | None
    field_footnotes: dict[str, tuple[str, ...]]   # e.g. {"price": ("F1",)}

@dataclass(frozen=True)
class OwnershipDoc:
    document_type: str; period_of_report: date | None; date_of_original_submission: date | None
    not_subject_to_section16: bool | None; issuer_cik: int; issuer_name: str; issuer_symbol: str | None
    owners: tuple[ReportingOwner, ...]; aff10b5one: bool | None; rows: tuple[OwnershipRow, ...]
    footnotes: dict[str, str]; remarks: str | None

def parse_ownership(xml: bytes) -> OwnershipDoc
def to_jsonable(doc: OwnershipDoc) -> dict   # dates → ISO strings, tuples → lists (golden files use this)
```

- `row_no` is 1-based, counted separately per `(table_kind, row_kind)`, in document order.
- `field_footnotes` keys are the names of the dataclass fields that carried a `footnoteId`.

- [ ] **Step 1: Write the failing tests:**

```python
OWNERSHIP_KEYS = ["form4_buy_single","form4_joint","form4a_original","form4a_amendment","form4_10b5_1_flag",
  "form4_10b5_1_footnote","form4_exercise_sale","form4_footnote_price","form4_value_owned","form3","form5"]

def _doc(key, fixture_bytes):
    return parse_ownership(SgmlFiling.from_txt(fixture_bytes(key)).xml_documents()[0].xml())

@pytest.mark.parametrize("key", OWNERSHIP_KEYS)
def test_matches_golden(key, fixture_bytes):
    assert to_jsonable(_doc(key, fixture_bytes)) == json.loads(golden_path(key).read_text())

@pytest.mark.parametrize("key", ["form4_buy_single", "form4_joint", "form4_10b5_1_flag", "form4_exercise_sale"])
def test_manifest_anchors(key, fixture_bytes, manifest):
    doc, exp = _doc(key, fixture_bytes), manifest[key]["expect"]
    tx = [r for r in doc.rows if r.table_kind == "nonderiv" and r.row_kind == "transaction"]
    assert doc.issuer_cik == exp["issuer_cik"]
    assert sorted(o.cik for o in doc.owners) == sorted(exp["owner_ciks"])
    assert [r.code for r in tx] == exp["codes"]
    if "first_nonderiv" in exp:
        f = exp["first_nonderiv"]
        assert (str(tx[0].transaction_date), tx[0].shares, tx[0].price, tx[0].shares_owned_after) == \
               (f["transaction_date"], f["shares"], f["price"], f["shares_owned_after"])

def test_aff10b5one(fixture_bytes):
    assert _doc("form4_10b5_1_flag", fixture_bytes).aff10b5one is True
    assert _doc("form4_buy_single", fixture_bytes).aff10b5one in (False, None)

def test_amendment_has_original_date(fixture_bytes, manifest):
    d = _doc("form4a_amendment", fixture_bytes)
    assert d.document_type == "4/A"
    assert str(d.date_of_original_submission) == manifest["form4a_amendment"]["expect"]["date_of_original_submission"]

INLINE = b"""<ownershipDocument><documentType>4</documentType>
<issuer><issuerCik>0001000001</issuerCik><issuerName>Acme</issuerName><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0002000001</rptOwnerCik><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>true</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
<transactionDate><value>2024-01-15-05:00</value></transactionDate>
<transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>100</value></transactionShares>
<transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><valueOwnedFollowingTransaction><value>5000</value></valueOwnedFollowingTransaction></postTransactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
</nonDerivativeTransaction></nonDerivativeTable>
<footnotes><footnote id="F1">Weighted average price.</footnote></footnotes></ownershipDocument>"""

def test_inline_gotchas():
    d = parse_ownership(INLINE); r = d.rows[0]
    assert d.issuer_cik == 1000001 and d.owners[0].is_officer is True and d.owners[0].is_director is False
    assert r.transaction_date == date(2024, 1, 15) and r.price is None and r.field_footnotes["price"] == ("F1",)
    assert r.shares_owned_after is None and r.value_owned_after == 5000.0
    assert d.footnotes == {"F1": "Weighted average price."}
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_parse_ownership.py`. Expected: FAIL (the module doesn't exist).

- [ ] **Step 3: Implement `parse_ownership`** with the xmlutil helpers. Rules:
  - Missing boolean relationship flags mean `False`.
  - CIKs are `int(...)` after stripping leading zeros.
  - `transactionTimeliness` goes to `timeliness`.
  - Derivative rows read `conversionOrExercisePrice`, `exerciseDate`, `expirationDate` and `underlyingSecurity/{underlyingSecurityTitle,underlyingSecurityShares}`.

- [ ] **Step 4: Generate the golden files.** Write a throwaway loop that dumps `to_jsonable` for each key into `tests/fixtures/golden/<key>.json`. Check each against the filing's sec.gov view (every row's code, shares, price and owned-after) before committing. Then run `uv run pytest tests/unit/test_parse_ownership.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): ownership document parser with golden tests`.

---

### Task A2: Form 144 parser

**Files:**
- Create: `backend/src/signals/ingest/parsers/form144.py`, `backend/tests/fixtures/golden/form144.json`
- Test: `backend/tests/unit/test_parse_form144.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Form144Doc:
    issuer_cik: int | None; issuer_name: str | None; seller_name: str | None; relationships: tuple[str, ...]
    security_class: str | None; broker: str | None; shares_to_sell: float | None; market_value_usd: float | None
    shares_outstanding: float | None; approx_sale_date: date | None; exchange: str | None
    acquired_how: str | None; acquired_date: date | None; plan_10b5_1_adopted: date | None
    sold_past_3m: tuple[tuple[date | None, float | None, float | None], ...]   # (sale date, shares, gross proceeds)

def parse_form144(xml: bytes) -> Form144Doc
```

- When the notice lists several securities lines, sum `shares_to_sell` and `market_value_usd` across them and keep the first line's class, broker, exchange and sale date.
- Element paths come from the recorded fixture and the SEC Form 144 XML technical specification. The golden file pins them.

- [ ] **Step 1: Write the failing tests.**
  - `test_form144_matches_golden` (as in A1).
  - `test_form144_anchors`: `issuer_cik`, `shares_to_sell`, `market_value_usd` and `str(approx_sale_date)` equal the manifest's `expect` values.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement. Generate the golden file and check it by eye against the filing.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): Form 144 parser`.

---

### Task A3: Ownership normalizer (canonical rows and feed item)

**Files:**
- Create: `backend/src/signals/ingest/normalize_insider.py`
- Test: `backend/tests/integration/test_normalize_insider.py`

**Interfaces:**
- `normalize_ownership(session: Session, filing: Filing, doc: OwnershipDoc) -> None`
- `classify_owner_type(owner: ReportingOwner) -> Literal["person", "entity"]`: `entity` when the owner is not an officer and not a director, and the name matches `\b(INC|INCORPORATED|LLC|L\.?L\.?C|LP|L\.?P|CORP|CORPORATION|CO|COMPANY|FUND|TRUST|HOLDINGS?|PARTNERS|CAPITAL|MANAGEMENT|GROUP|LTD|LIMITED|ADVISORS?|N\.?A)\b`, case-insensitive. Otherwise `person`.
- `plan_flag_for_row(row: OwnershipRow, doc: OwnershipDoc) -> PlanFlag`:
  - `flag` when `doc.aff10b5one` is true.
  - Otherwise `footnote` when any footnote referenced by the row's `field_footnotes`, or `doc.remarks`, matches `10b5-?1` (case-insensitive).
  - Otherwise `none`.

**Writes, all within the caller's transaction:**
1. Upsert `issuers(cik, name)`, keeping any existing sector and SIC. Then `record_ticker_evidence(session, doc.issuer_cik, doc.issuer_symbol, filing.filed_date, "ownership")`.
2. Upsert `owners`. Upsert `owner_roles`, where `roles = normalize_roles(...)` and `first_filed`/`last_filed` are the min and max of the filing dates. Insert `filing_owners`.
3. Delete this accession's rows from `insider_transactions` and `insider_holdings`, then insert every row with:
   - `owner_group = owner_group_key(owner ciks)`
   - `value_usd = shares * price` when both are known
   - `footnotes` = the texts of the ids that row references
   - the `plan_10b5_1` flag from `plan_flag_for_row`
   - `flags`: `price_missing` for P and S rows without a price
4. Upsert `feed_items`:
   - `direction` compares the P and S row values: `buy` if P > S, `sell` if S > P, otherwise `other`.
   - `value_usd`, `shares` and the VWAP `price` come from the dominant side.
   - `codes` = the sorted distinct codes.
   - `plan_10b5_1` = `flag` if any row is flagged, else `footnote` if any row is, else `none`.
   - `top_role` = `top_role` over all owners' roles.
   - `owner_names` = the names joined with `"; "`.
   - `summary`: `summarize_trade(...)` for buys and sells. For Form 3, `"Initial holdings: N securities"`. Otherwise the code labels joined with `", "`.
   - `lag_days` = SEC business days from the first P or S transaction date to the acceptance date (None when there's no P or S).
   - `first_trade_date` is set.

- [ ] **Step 1: Write the failing tests.** Each one ingests fixtures through `ingest_raw`, with the registry reset and a handler that calls `parse_ownership` and then `normalize_ownership`. A local helper `load(key)` does this.

```python
def test_joint_filing_links_all_owners(session, manifest):
    acc = load(session, "form4_joint")
    owners = session.scalars(select(FilingOwner.owner_cik).where(FilingOwner.accession_no == acc)).all()
    assert sorted(owners) == sorted(manifest["form4_joint"]["expect"]["owner_ciks"])
    groups = set(session.scalars(select(InsiderTransaction.owner_group).where(InsiderTransaction.accession_no == acc)))
    assert groups == {owner_group_key(owners)}

def test_idempotent(session):
    load(session, "form4_buy_single"); n1 = session.scalar(select(func.count(InsiderTransaction.id)))
    load(session, "form4_buy_single", force=True); assert session.scalar(select(func.count(InsiderTransaction.id))) == n1

def test_plan_flags(session):
    a = load(session, "form4_10b5_1_flag"); b = load(session, "form4_10b5_1_footnote")
    assert set(plan_flags(session, a, code="S")) == {"flag"}
    assert "footnote" in set(plan_flags(session, b, code="S"))

def test_feed_item_for_purchase(session, manifest):
    acc = load(session, "form4_buy_single"); fi = session.get(FeedItem, acc)
    assert fi.direction == "buy" and fi.summary.startswith("Bought ") and "P" in fi.codes

def test_owner_type_heuristic():
    mk = lambda n, **k: ReportingOwner(cik=1, name=n, is_director=k.get("d", False), is_officer=k.get("o", False),
                                     officer_title=None, is_ten_pct_owner=True, is_other=False, other_text=None)
    assert classify_owner_type(mk("BERKSHIRE HATHAWAY INC")) == "entity"
    assert classify_owner_type(mk("BUFFETT WARREN E")) == "person"
    assert classify_owner_type(mk("SMITH CAPITAL JOHN", o=True)) == "person"

def test_ticker_evidence_recorded(session):
    acc = load(session, "form4_buy_single")
    issuer = session.get(Filing, acc).issuer_cik
    assert session.scalar(select(func.count()).select_from(TickerEvidence).where(TickerEvidence.issuer_cik == issuer)) == 1
```

  `plan_flags(session, acc, code)` is a local helper returning the `plan_10b5_1` values for that accession and code.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_normalize_insider.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_normalize_insider.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): normalize ownership filings into canonical rows and feed items`.

---

### Task A4: Amendment linking

**Files:**
- Create: `backend/src/signals/ingest/amendments.py`
- Test: `backend/tests/integration/test_amendments.py`

**Interfaces:**
- `link_amendment(session, amendment_accession: str) -> str | None`:
  1. The candidates are filings with `form_type` equal to the amendment's type minus `/A`, the same `issuer_cik`, at least one `filing_owners` CIK in common, and `filed_date` equal to the amendment's `filings.original_filed_date`. Each candidate's `accession_no` must differ from the amendment's.
  2. If there are several, pick the one with the most overlapping `transaction_date` values, breaking ties by the latest `accepted_at`.
  3. Set `filings.amends_accession` on the amendment. Set `superseded_by = <amendment accession>` on the original's `insider_transactions` and `insider_holdings`. Remove `orphan_amendment` from the amendment rows' `flags`.
  4. With no candidate, or with `original_filed_date` NULL, add `orphan_amendment` to the amendment rows' `flags` and return `None`.
- `relink_orphans(session) -> int`: calls `link_amendment` for every amendment whose rows carry `orphan_amendment`. Returns how many it linked.
- The date comes from the new `filings.original_filed_date` column (foundation schema). A3's normalizer sets it from `doc.date_of_original_submission`, and the bulk loader (A10) from `DATE_OF_ORIG_SUB`.

- [ ] **Step 1: Write the failing tests:**
  - `test_amendment_supersedes_original`: load `form4a_original`, then `form4a_amendment`. Every original transaction row has `superseded_by == amendment accession`, and the amendment's `filings.amends_accession == original accession`.
  - `test_orphan_then_relinked`: load the amendment first, and its rows carry `orphan_amendment`. Then load the original and call `relink_orphans(session) == 1`. The flag is gone and the original is superseded.
  - `test_multiple_candidates_pick_overlap`: with the factories, build two originals filed on the same day by the same owner and issuer. Their transaction dates are `[2024-01-10]` and `[2024-01-11]`. The amendment rows' dates are `[2024-01-11]`, so the second original is chosen.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement. Update A3's `normalize_ownership` to set `filing.original_filed_date = doc.date_of_original_submission`, and to call `link_amendment(session, filing.accession_no)` when `doc.document_type.endswith("/A")`.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_amendments.py tests/integration/test_normalize_insider.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): link ownership amendments and relink orphans`.

---

### Task A5: Form 144 normalizer

**Files:**
- Create: `backend/src/signals/ingest/normalize_form144.py`
- Test: `backend/tests/integration/test_normalize_form144.py`

**Interfaces:** `normalize_form144(session, filing: Filing, doc: Form144Doc, sgml: SgmlFiling) -> None`

- `issuer_cik` is `doc.issuer_cik`, or else `sgml.ciks_by_role["SUBJECT COMPANY"][0]`. `filer_cik` is `sgml.primary_cik()`.
- It upserts `issuers` (the name only when new), `owners` for the filer, and the `form144_notices` row.
- It upserts `feed_items` with `direction="sell"`, `codes=["144"]` and `summary = f"Plans to sell {shares:,.0f} sh (~${value:,.0f}) around {date:%b %d, %Y}"`, leaving out any unknown part.

- [ ] **Step 1: Write the failing test.** `test_form144_row_and_feed`: load the `form144` fixture. The notice's `shares_to_sell`, `market_value_usd` and `approx_sale_date` equal the manifest's, and the feed item summary starts with `"Plans to sell "`.

- [ ] **Step 2:** Run the test. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the test. Expected: pass.

- [ ] **Step 5: Commit** with message `feat(ingest): normalize Form 144 notices`.

---

### Task A6: Register the handlers

**Files:**
- Modify: `backend/src/signals/ingest/handlers/insider.py` (your stub)
- Test: `backend/tests/integration/test_handlers_insider.py`

**Interfaces:**
- `handle_ownership(session, sgml, filing, ctx) -> None`: the first XML document whose root is `ownershipDocument`, then parse, then normalize (which also links amendments).
- `handle_form144(session, sgml, filing, ctx) -> None`
- At module import: `register_handler(INSIDER_FORMS, handle_ownership)` and `register_handler(FORM144_FORMS, handle_form144)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_all_ownership_fixtures_ingest`: for every ownership key and `form144`, calling `ingest_raw(session, fixture_bytes(key), source="test", ...)` gives status `parsed`. Import `signals.ingest.handlers` first.
  - `test_registered_forms`: `registered_forms() >= INSIDER_FORMS | FORM144_FORMS`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: pass.

- [ ] **Step 5: Commit** with message `feat(ingest): register insider and Form 144 handlers`.

---

### Task A7: Live feed poller

**Files:**
- Create: `backend/src/signals/ingest/feed.py`
- Test: `backend/tests/integration/test_feed_poll.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FeedEntry: accession_no: str; form_type: str; cik: int; company: str; role: str | None; updated: datetime
@dataclass(frozen=True)
class PollResult: pages: int; entries: int; new: int; errors: int; issuer_ciks: frozenset[int]; owner_ciks: frozenset[int]; filer_ciks: frozenset[int]

def feed_url(form_type: str, start: int) -> str
def parse_atom(xml: bytes) -> list[FeedEntry]
def poll_feed(client: SecClient, session_factory, *, form_types: Sequence[str] = FEED_POLL_FORMS, max_pages: int = 5,
              now: datetime, settings: Settings, archive: RawArchive) -> PollResult
```

- `feed_url` returns `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={quote_plus(form)}&company=&dateb=&owner=include&start={n}&count=100&output=atom`.
- **Parsing an entry:**
  - The accession comes from `<id>` (`…accession-number=XXXX`) or the link.
  - The form comes from `<category term>`.
  - The CIK and role come from the title pattern `^(?P<form>.+?) - (?P<company>.+) \((?P<cik>\d{10})\) \((?P<role>[^)]+)\)$`.
  - `updated` is timezone-aware.
- **For each base form**, the allowed terms are `{form, form + "/A"}`. Fetch pages `start = 0, 100, …` with `Priority.LIVE`, archiving each as `("feed", f"{form}-{now:%Y%m%dT%H%M%S}-{start}", "xml")`.
  - Entries are deduped by accession across pages.
  - Stop after a page that contains any accession already in `filings`, or after `max_pages`.
  - Each new accession goes through `ingest_accession(..., source="feed", priority=Priority.LIVE, first_seen_at=now)` in its own session, committing per filing. An error increments `errors` and moves on.
- **After the loop:**
  - `set_state(session, "live_poll_last_success", {"at": now.isoformat(), "new": new})`.
  - If any issuers or owners are new, call `request_job(session, "analytics_incremental", {"issuer_ciks": [...], "owner_ciks": [...]})`.
  - If any 13F filers are new, call `request_job(session, "fund_changes", {"filer_ciks": [...]})`.

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_atom_fixture`: `len(entries) == manifest["atom_form4_p1"]["expect"]["n_entries"]`, and the first entry's accession, form type and CIK equal the manifest `first`.
  - `test_filters_prefix_matches`: polling form `"4"` over the `atom_form4_424b2` page ingests no `424B2` accession. Assert on the MockRouter's request URLs: no `.txt` fetched for them.
  - `test_poll_paginates_until_known_accession`: start with an empty database and the MockRouter serving `start=0` → p1, `start=100` → p2, and p2's last accession pre-seeded as parsed. Exactly 2 feed pages are requested and every other unique accession is fetched once.
  - `test_dedupes_reporting_and_issuer_entries`: a synthetic Atom with the same accession twice (Reporting and Issuer) leads to one `.txt` request.
  - `test_requests_incremental_analytics`: after a poll that ingests `form4_buy_single`, a `job_requests` row of kind `analytics_incremental` exists and its `issuer_ciks` contains the fixture issuer.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_feed_poll.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_feed_poll.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): live Atom feed poller with pagination and dedupe`.

---

### Task A8: Index parsing and nightly reconcile

**Files:**
- Create: `backend/src/signals/ingest/indexes.py`
- Test: `backend/tests/integration/test_indexes.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class IndexEntry: form_type: str; company: str; cik: int; date_filed: date; filename: str; accession_no: str
@dataclass(frozen=True)
class ReconcileResult: day: date; listed: int; missing: int; ingested: int; errors: int

def daily_index_url(day: date) -> str
def full_index_url(year: int, quarter: int) -> str
def parse_form_idx(text: str) -> list[IndexEntry]
def reconcile_day(client, session_factory, day: date, *, settings, archive, forms: frozenset[str] = TRACKED_FORMS) -> ReconcileResult
```

- `daily_index_url` returns `https://www.sec.gov/Archives/edgar/daily-index/{Y}/QTR{q}/form.{YYYYMMDD}.idx`.
- `full_index_url` returns `https://www.sec.gov/Archives/edgar/full-index/{Y}/QTR{q}/form.idx`.
- `parse_form_idx` parses each data row (after the dashed line) right-anchored: the file name, date and CIK come off the right end, and the form type is everything before the first run of 2+ spaces (form types can contain single spaces, e.g. `SCHEDULE 13D`, `1-A POS`). Do not derive columns from the header: in daily indexes it wraps onto two lines (see the `daily_index` manifest `structure_note`). Dates are `YYYYMMDD` (daily) or `YYYY-MM-DD` (full). `accession_no` is the file name's last path part without `.txt`.
- `reconcile_day`:
  - A 404 on the index (weekend or holiday) returns zeros.
  - Entries with a form in `forms` that are missing from `filings` are ingested with `source="daily_index"`, one commit per filing.
  - It is wrapped in `track_run(..., "reconcile_daily")` with `missed = missing`.

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_daily_index_fixture`: the count equals the manifest `n_entries`, and the `sample` entry fields match. Every form type containing a space (for example `SCHEDULE 13G/A`) parses whole.
  - `test_parse_full_index_fixture_dashed_dates`: the count equals the manifest's.
  - `test_reconcile_ingests_only_missing`: build a three-line index text (Form 4 fixtures A, B, C) served at the daily URL, with A pre-seeded as parsed. The result is `listed == 3`, `missing == 2` and `ingested == 2`, and exactly two `.txt` requests are made.
  - `test_reconcile_holiday_404`: the index URL returns 404, so the result is `listed == 0`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): daily/full index parsing and nightly reconcile`.

---

### Task A9: Resumable gap fill

**Files:**
- Create: `backend/src/signals/ingest/gap_fill.py`
- Test: `backend/tests/integration/test_gap_fill.py`

**Interfaces:**
- `GapFillResult(listed: int, ingested: int, skipped_existing: int, errors: int)`
- `gap_fill(client, session_factory, *, form_types: Collection[str], start: date, end: date, settings, archive, progress: dict, save_progress: Callable[[dict], None], source: str = "full_index") -> GapFillResult`
- **Iteration:** go quarter by quarter from `start` to `end`. Fetch `full_index_url` for past quarters. For the current quarter, use the daily indexes for each SEC business day from the quarter start (or `start`) to `end`, because the full index lags.
- **Filtering:** keep entries with `form_type in form_types` and `start <= date_filed <= end` that aren't already parsed.
- **Resuming:** `progress["quarters_done"]` lists `"2024Q3"` style keys. `progress["current"] = {"quarter": "2024Q4", "offset": n}` records the next entry index and is saved every 200 filings through `save_progress`.

- [ ] **Step 1: Write the failing tests:**
  - `test_filters_forms_and_dates`: serve a full index with a mix of forms and dates. Only the `144` rows inside the date range are fetched.
  - `test_resumes_from_progress`: with `progress={"quarters_done": ["2025Q1"]}`, the 2025Q1 URL is never requested.
  - `test_saves_offset_every_200`: a synthetic index of 450 rows, all served. `save_progress` is called with offsets `[200, 400]`, and then the quarter is marked done.

- [ ] **Step 2:** Run the tests. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run the tests. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): resumable per-filing gap fill`.

---

### Task A10: Bulk loader for the Insider Transactions Data Sets

**Files:**
- Create: `backend/src/signals/ingest/bulk_345.py`
- Test: `backend/tests/integration/test_bulk_345.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class DatasetLink: name: str; url: str; year: int; quarter: int
@dataclass(frozen=True)
class BulkLoadResult: accessions: int; skipped_existing: int; transactions: int; holdings: int

def list_345_datasets(html: str, base_url: str = "https://www.sec.gov") -> list[DatasetLink]
def load_345_zip(session, zip_bytes: bytes) -> BulkLoadResult
def apply_acceptance_times(session) -> int
```

- `list_345_datasets` returns every `<a href>` matching `(\d{4})q([1-4])_form345\.zip`, made absolute and sorted by `(year, quarter)`.
- `apply_acceptance_times` updates `filings` and `feed_items` from `filing_acceptance` wherever `accepted_at IS NULL`, and sets `accepted_at_source='submissions'`.

**Loading method.** Every step runs inside the caller's transaction:
1. **Decode and stage.** For each TSV, decode it as `utf-8` with `errors="replace"` and COPY it into a `TEMP` table (all TEXT columns, created from the header, `ON COMMIT DROP`). Use `COPY … FROM STDIN (FORMAT csv, DELIMITER E'\t', QUOTE E'\x01', HEADER true)`, because SEC TSVs are unquoted and may contain backslashes.
2. **Skip existing filings.** Accessions already in `filings` with `parse_status='parsed'` count as `skipped_existing` and are removed from staging.
3. **`filings` rows:**
   - `form_type = DOCUMENT_TYPE`, `filed_date = to_date(FILING_DATE,'DD-MON-YYYY')`, `issuer_cik = ISSUERCIK::bigint`.
   - `primary_cik` = the lowest reporting-owner CIK.
   - `source='bulk_345'`, `parse_status='parsed'`, `raw_path='bulk:<zip name>'`.
   - `accepted_at` comes from `filing_acceptance` when present; otherwise NULL with `accepted_at_source='missing'`.
4. **Owners and roles:**
   - Owners come from REPORTINGOWNER.
   - Flags: `is_director` when RPTOWNER_RELATIONSHIP contains `director` (case-insensitive), `is_officer` for `officer`, `is_ten_pct_owner` for `tenpercent` or `10%`, and `is_other` for `other`. The officer title is `RPTOWNER_TITLE`.
   - `owner_roles.roles` is computed in Python with `normalize_roles`, over the distinct owner/issuer/title/flag combinations.
5. **Owner groups:** `owner_group` must equal `owner_group_key` (numeric sort). Build it in SQL with `array_to_string(ARRAY(SELECT DISTINCT c::bigint FROM … ORDER BY 1), '|')`.
6. **Transactions and holdings** come from NONDERIV_TRANS, DERIV_TRANS, NONDERIV_HOLDING and DERIV_HOLDING, with `row_no = row_number() OVER (PARTITION BY accession ORDER BY <SK>::bigint)`. Every `*_FN` column is split on `,` into `field_footnotes`, and the footnote texts come from FOOTNOTES.
7. **10b5-1:** `plan_10b5_1` is `footnote` when a referenced footnote text or the SUBMISSION `REMARKS` matches `10b5-?1` (case-insensitive). If SUBMISSION has any column whose name contains `10B5` with value `1` or `true`, the flag is `flag` instead.
8. **Ticker evidence:** call `record_ticker_evidence` for each distinct `(ISSUERCIK, ISSUERTRADINGSYMBOL, FILING_DATE)`, then `rebuild_tickers` for the touched issuers.
9. **Amendments and feed items.** Set `filings.original_filed_date = to_date(DATE_OF_ORIG_SUB,'DD-MON-YYYY')`. Call `link_amendment(session, acc)` for every amendment accession, then `relink_orphans(session)`. Finally build `feed_items` in Python batches of 5,000 with the same rules as A3.

- [ ] **Step 1: Write the failing tests** (using `bulk_345_slice` and `listing_345_html`):
  - `test_list_datasets`: `len(links) == manifest["listing_345_html"]["expect"]["n_links"]`. The first is `2006q1_form345.zip`, every URL starts with `https://www.sec.gov/`, and the list is sorted.
  - `test_load_slice_counts`: `accessions == len(expect["accessions"])`, and the transaction and holding counts equal the manifest numbers (nonderivative plus derivative).
  - `test_owner_group_matches_python`: for `expect["joint_accession"]`, the stored `owner_group == owner_group_key(<that accession's owner CIKs>)`.
  - `test_plan_flag_footnote_in_bulk`: the `footnote_10b5_1_accession` rows include `plan_10b5_1 == "footnote"`.
  - `test_skips_accessions_already_parsed`: pre-seed one slice accession as parsed from XML. `skipped_existing == 1`, and that accession's rows aren't duplicated.
  - `test_idempotent`: loading twice gives the same row counts.
  - `test_apply_acceptance_times`: insert a `filing_acceptance` row for one loaded accession, run `apply_acceptance_times`, and both `filings.accepted_at` and `feed_items.accepted_at` are set.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_bulk_345.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_bulk_345.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(ingest): bulk loader for SEC Insider Transactions Data Sets`.

---

### Task A11: Jobs

**Files:**
- Modify: `backend/src/signals/ingest/jobs_insider.py` (your stub)
- Test: `backend/tests/integration/test_jobs_insider.py`

**Interfaces** (each is registered through `@register_job`):
- **`live_poll`**, `interval_seconds=60`: returns `{"skipped": "outside window"}` unless `is_sec_business_day(today_et)` and `06:00 <= now_et < 22:00`. Otherwise it runs `poll_feed` and returns the `PollResult` as a dict.
- **`reconcile_daily`**, `cron={"hour": 6, "minute": 30}`: reconciles each SEC business day after `app_state["reconcile_last_day"]`, up to yesterday and at most 7 days back, then stores the last day.
- **`backfill_insiders`** (on request). Its steps are resumable through `ctx.progress`:
  1. Fetch the listing page `https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets` and list the datasets.
  2. For each dataset from `settings.backfill_start`'s quarter that isn't in `progress["datasets_done"]`, fetch the ZIP (archived as `("bulk", name, "zip")`), run `load_345_zip`, commit, and record it.
  3. `apply_acceptance_times`.
  4. `gap_fill` for `INSIDER_FORMS`, from the day after the last dataset's quarter end through yesterday.
  5. `gap_fill` for `FORM144_FORMS`, from `settings.form144_start` through yesterday.

  It returns a summary dict.
- **`bulk_check_insiders`**, `cron={"day_of_week": "mon", "hour": 3, "minute": 0}`: loads any listed dataset missing from `app_state["bulk_345_loaded"]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_jobs_registered`: after `load_all_jobs()`, `JOBS["live_poll"].interval_seconds == 60`, `JOBS["reconcile_daily"].cron == {"hour": 6, "minute": 30}`, and `"backfill_insiders" in JOBS`.
  - `test_live_poll_outside_window`: with a `ctx.now` of Saturday 2024-06-08 10:00 ET, the job returns `{"skipped": "outside window"}` and makes no HTTP requests.
  - `test_backfill_insiders_resumes`: a MockRouter serves the listing (2 datasets) and the slice ZIP. With `progress={"datasets_done": [first name]}`, only the second ZIP is requested. The gap-fill steps are stubbed with `monkeypatch`.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_jobs_insider.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest -q`. Expected: the whole backend suite passes.

- [ ] **Step 5: Commit** with message `feat(ingest): insider jobs (live poll, reconcile, backfill, bulk check)`.
