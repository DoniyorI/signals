# Foundation Implementation Plan (main agent)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every shared contract (schema, domain helpers, SEC client, fixtures, ingest pipeline, jobs, API schemas, frontend skeleton, Compose) so the six workstreams can build in parallel without touching each other's files.

**Architecture:** One Python package, `backend/src/signals`, plus a Vite React app in `frontend/`. The foundation writes the modules everyone imports and leaves empty stub modules for each workstream to fill.

**Tech Stack:** See `00-overview.md`.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`

## Global Constraints

Everything in `00-overview.md` › Global Constraints applies. On top of that:
- `.env` is created with mode 600 and must be matched by `.gitignore` before any commit.
- `SEC_USER_AGENT` is the user's full name and Gmail address, approved by the user on 2026-09-27. The value lives only in `.env` and never in committed files.
- The Alpaca key ID and secret are the pair the user pasted on 2026-09-27. They are written only to `.env` and never echoed in chat.

## Review Focus

Covered by `00-overview.md`. The foundation owns none of the five, but Task 3's calendar tests (Good Friday, Columbus Day, early close) underpin item 2.

## Workstream-owned stub modules

The foundation creates these stubs (docstring only). Each is owned and filled by the workstream listed.

| Stub | Owner |
|---|---|
| `backend/src/signals/ingest/handlers/insider.py`, `ingest/jobs_insider.py` | A |
| `backend/src/signals/ingest/handlers/funds.py`, `ingest/jobs_funds.py` | B |
| `backend/src/signals/reference/jobs.py`, `prices/jobs.py` | C |
| `backend/src/signals/analytics/curves.py` (stub raises `NotImplementedError`), `analytics/jobs.py` | D |
| `backend/src/signals/api/routers/*.py` (bodies raise `NotImplementedError`, which returns 501) | E |
| Everything under `frontend/src/pages/` | F |

---

### Task 1: Prerequisites, scaffold, settings, Alpaca feed check

**Files:**
- Create: `.gitignore`, `.env.example`, `.env` (not committed, chmod 600), `docker-compose.yml` (only the `db` service for now), `backend/pyproject.toml`, `backend/src/signals/__init__.py`, `backend/src/signals/config.py`, `backend/tests/unit/test_config.py`, `scripts/probe_alpaca.py`

**Interfaces:**
- Produces: `signals.config.Settings` (pydantic-settings `BaseSettings`) and `signals.config.get_settings() -> Settings` (`functools.cache`).

**Settings fields** (env var = upper-case name):

| Field | Type | Default |
|---|---|---|
| `database_url` | `str` | `"postgresql+psycopg://signals:signals@127.0.0.1:5432/signals"` |
| `sec_user_agent` | `str` | required. The validator requires a space and an `@`. |
| `sec_rate_limit` | `float` | `8.0` |
| `raw_archive_dir` | `Path` | `Path("data/raw")` |
| `backfill_start` | `date` | `2016-01-01` |
| `form144_start` | `date` | `2023-04-13` |
| `stakes_start` | `date` | `2024-12-18` |
| `price_primary` | `Literal["alpaca","yfinance"]` | `"alpaca"` |
| `alpaca_api_key` | `str \| None` | `None` |
| `alpaca_secret_key` | `SecretStr \| None` | `None` |
| `alpaca_feed` | `Literal["sip","iex"]` | `"sip"` |
| `alpaca_data_url` | `str` | `"https://data.alpaca.markets"` |
| `openfigi_api_key` | `SecretStr \| None` | `None` |
| `tracked_funds_top_n` | `int` | `500` |
| `tracked_funds_max_positions` | `int` | `300` |
| `log_json` | `bool` | `True` |

The config sets `env_file=(".env", "../.env")` and `extra="ignore"`.

- [ ] **Step 1: Prerequisite check.** Run `docker info --format '{{.ServerVersion}}'`. If the daemon isn't running, ask the user to open Docker Desktop and wait for the reply. Then run `uv --version` and `node --version`.

- [ ] **Step 2: Write `.gitignore`.** It covers: `.env`, `data/`, `**/__pycache__/`, `.venv/`, `node_modules/`, `frontend/dist/`, `frontend/test-results/`, `frontend/playwright-report/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, and `.DS_Store`.

- [ ] **Step 3: Write `.env.example`** with every Settings key, plus `POSTGRES_PASSWORD=signals`. Secrets are left empty.

- [ ] **Step 4: Write `.env`** with the approved `SEC_USER_AGENT`, `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` from the user's 2026-09-27 message, and `POSTGRES_PASSWORD=signals`. Then run `chmod 600 .env` and `git check-ignore .env`. Expected output: `.env`.

- [ ] **Step 5: Write `docker-compose.yml`** with only the `db` service:
  - image `postgres:17`
  - env `POSTGRES_USER=signals`, `POSTGRES_PASSWORD=${POSTGRES_PASSWORD}`, `POSTGRES_DB=signals`
  - ports `127.0.0.1:5432:5432`
  - volume `pgdata:/var/lib/postgresql/data`
  - healthcheck `pg_isready -U signals`, every 5 s

  Run `docker compose up -d db`, then `docker compose ps`. Expected: `db` is `healthy`.

- [ ] **Step 6: Write `backend/pyproject.toml`.**
  - Hatchling build, packages in `src/signals`, script `signals = "signals.cli:app"`.
  - Dependencies: `fastapi>=0.141`, `uvicorn[standard]>=0.54`, `sqlalchemy>=2.1`, `alembic>=1.20`, `psycopg[binary]>=3.3`, `pydantic>=2.13`, `pydantic-settings>=2.15`, `httpx>=0.28`, `apscheduler>=3.11,<4`, `typer>=0.27`, `structlog>=26.1`, `lxml>=6.1`, `pandas>=3.0`, `numpy>=2.5`, `exchange-calendars>=4.13`, `holidays>=0.105`, `rapidfuzz>=3.14`, `yfinance>=1.7`, `tzdata`.
  - Dev group: `pytest>=9.1`, `ruff>=0.16`, `pyright>=1.1.414`, `pandas-stubs>=3.0`, `lxml-stubs`.
  - `[tool.pytest.ini_options]`: `testpaths=["tests"]`, `addopts="-q"`.
  - `[tool.ruff]`: `line-length=100`, `target-version="py313"`, lint rules `["E","F","I","B","UP","SIM","RUF"]`.
  - `[tool.pyright]`: `include=["src","tests"]`, `pythonVersion="3.13"`, `typeCheckingMode="standard"`.

  Run `cd backend && uv sync`. Expected: resolves and creates `uv.lock`.

- [ ] **Step 7: Write the failing tests** in `backend/tests/unit/test_config.py`:

```python
import pytest
from datetime import date
from pydantic import ValidationError
from signals.config import Settings

def test_requires_sec_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

def test_rejects_user_agent_without_email():
    with pytest.raises(ValidationError):
        Settings(sec_user_agent="Doniyor", _env_file=None)

def test_defaults():
    s = Settings(sec_user_agent="Test User test@example.com", _env_file=None)
    assert s.sec_rate_limit == 8.0
    assert s.backfill_start == date(2016, 1, 1)
    assert s.form144_start == date(2023, 4, 13)
    assert s.stakes_start == date(2024, 12, 18)
    assert (s.tracked_funds_top_n, s.tracked_funds_max_positions) == (500, 300)
    assert (s.price_primary, s.alpaca_feed) == ("alpaca", "sip")
```

- [ ] **Step 8:** Run `uv run pytest tests/unit/test_config.py`. Expected: FAIL (`ModuleNotFoundError: signals.config`).

- [ ] **Step 9: Implement `Settings` and `get_settings`** in `config.py`. `sec_user_agent` gets a `field_validator` that raises `ValueError("SEC_USER_AGENT must be 'Name email@domain'")` unless the value contains both `" "` and `"@"`.

- [ ] **Step 10:** Run `uv run pytest -q && uv run ruff check && uv run pyright`. Expected: 3 passed, no lint or type errors.

- [ ] **Step 11: Alpaca feed check.** Write `scripts/probe_alpaca.py`. It loads `Settings`, then requests `GET {alpaca_data_url}/v2/stocks/bars?symbols=SPY&timeframe=1Day&start=2016-01-04T00:00:00Z&end=2016-01-09T00:00:00Z&adjustment=raw&feed=sip` with headers `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`. It prints `sip ok: <n> bars`, or `sip denied: <status> <body[:200]>`.

  Run `cd backend && uv run python ../scripts/probe_alpaca.py`.
  - Expected: `sip ok: 5 bars`.
  - If it prints `sip denied`, set `PRICE_PRIMARY=yfinance` in `.env` and tell the user in one line.

- [ ] **Step 12: Commit** (`.env` must not be staged):

```bash
git add .gitignore .env.example docker-compose.yml backend/pyproject.toml backend/uv.lock backend/src backend/tests scripts/probe_alpaca.py
git commit -m "chore: scaffold backend, settings and Postgres service" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Domain types, accession numbers, owner groups, roles

**Files:**
- Create: `backend/src/signals/domain/__init__.py`, `domain/types.py`, `domain/accession.py`, `domain/owner_group.py`, `domain/roles.py`, `domain/portfolio.py`
- Test: `backend/tests/unit/test_domain_pure.py`

**Interfaces (produces):**

`domain/types.py`. These are `StrEnum`s and constants. Values are exact.
- `Direction`: `buy`, `sell`, `other`
- `Basis`: `filed`, `executed`
- `Horizon`: `1m`, `3m`, `6m`, `12m`, with `HORIZON_TRADING_DAYS = {1m: 21, 3m: 63, 6m: 126, 12m: 252}`
- `Window`: `ytd`, `1y`, `3y`, `5y`, with `WINDOW_TRADING_DAYS = {1y: 252, 3y: 756, 5y: 1260}`
- `Role`:
  - Members: `CEO="CEO"`, `CFO="CFO"`, `COO="COO"`, `PRESIDENT="President"`, `CHAIR="Chair"`, `GENERAL_COUNSEL="General Counsel"`, `OTHER_OFFICER="Other officer"`, `DIRECTOR="Director"`, `TEN_PCT_OWNER="10% owner"`, `OTHER="Other"`.
  - `ROLE_PRIORITY` in that order, except President sits before COO: CEO, CFO, PRESIDENT, COO, CHAIR, GENERAL_COUNSEL, OTHER_OFFICER, DIRECTOR, TEN_PCT_OWNER, OTHER.
- `PlanFlag`: `flag`, `footnote`, `none`
- `ChangeType`: `NEW`, `ADD`, `TRIM`, `EXIT`, `SAME`
- `ProfileKind`: `insider`, `fund`
- `Confidence`: `low`, `medium`, `high`
- `RiskLabel`: `low`, `medium`, `high`
- `ParseStatus`: `pending`, `parsed`, `error`, `skipped`
- `JobStatus`: `requested`, `running`, `done`, `failed`
- `Sector`: `Materials`, `Communication Services`, `Energy`, `Financials`, `Industrials`, `Technology`, `Consumer Staples`, `Real Estate`, `Utilities`, `Health Care`, `Consumer Discretionary`
- `SECTOR_ETF`: Materials XLB, Communication Services XLC, Energy XLE, Financials XLF, Industrials XLI, Technology XLK, Consumer Staples XLP, Real Estate XLRE, Utilities XLU, Health Care XLV, Consumer Discretionary XLY
- `BENCHMARK_SYMBOLS = ("SPY", "QQQ", *SECTOR_ETF.values())`
- `Badge`: `cluster_buy`, `late_filing`, `first_buy_2y`, `dip_buy`, `big_stake`, `form144_matched`, `top_exec`
- Form sets:
  - `INSIDER_FORMS = frozenset({"3","3/A","4","4/A","5","5/A"})`
  - `FORM144_FORMS = frozenset({"144","144/A"})`
  - `FUND_FORMS = frozenset({"13F-HR","13F-HR/A","13F-NT","13F-NT/A"})`
  - `STAKE_FORMS = frozenset({"SCHEDULE 13D","SCHEDULE 13D/A","SCHEDULE 13G","SCHEDULE 13G/A"})`
  - `TRACKED_FORMS` = the union of the four
  - `FEED_POLL_FORMS = ("3","4","5","144","13F-HR","SCHEDULE 13D","SCHEDULE 13G")`
- `CODE_LABELS`: `P` "Open-market buy", `S` "Open-market sale", `A` "Grant/award", `M` "Option exercise", `X` "In-the-money exercise", `O` "Out-of-the-money exercise", `F` "Tax withholding", `G` "Gift", `C` "Conversion", `D` "Disposition to issuer", `E` "Short derivative expired", `H` "Long derivative expired", `I` "Discretionary transaction", `J` "Other", `L` "Small acquisition", `U` "Tender in change of control", `W` "Will or inheritance", `Z` "Voting trust"

`domain/accession.py`:
- `normalize_accession(s: str) -> str`: accepts 18 digits, or the dashed form. Anything else raises `ValueError`.
- `accession_nodash(s: str) -> str`
- `filing_txt_url(cik: int, accession: str) -> str`
- `filing_index_url(cik: int, accession: str) -> str`

`domain/owner_group.py`:
- `owner_group_key(ciks: Iterable[int]) -> str`: unique CIKs sorted numerically and joined with `|`. An empty input raises `ValueError`.
- `owner_group_ciks(key: str) -> list[int]`

`domain/roles.py`:
- `normalize_roles(officer_title: str | None, *, is_director: bool, is_officer: bool, is_ten_pct_owner: bool, is_other: bool) -> list[Role]`
- `top_role(roles: Iterable[Role]) -> Role | None`

`domain/portfolio.py`. These pure helpers are shared by analytics (D) and the API (E):
- `effective_n(weights: Sequence[float]) -> float | None`: normalizes, then `1 / Σ w²`. `None` for an empty input.
- `top5_weight(weights: Sequence[float]) -> float | None`: the share of the five largest normalized weights.
- `allocation_slices(values: Mapping[str, float], labels: Mapping[str, str] | None = None) -> list[dict]`: dicts `{"key", "label", "value_usd", "weight"}` sorted by value descending. The label defaults to the key.
- `fund_high_conviction(weights: Sequence[float | None], changes: Sequence[str], values: Sequence[float]) -> list[bool]`: true for `weight >= 0.05`, or for `change == "NEW"` with a value rank (1 = largest) of 20 or better.

- [ ] **Step 1: Write the failing tests:**

```python
from signals.domain.accession import normalize_accession, accession_nodash, filing_txt_url, filing_index_url
from signals.domain.owner_group import owner_group_key, owner_group_ciks
from signals.domain.roles import normalize_roles, top_role
from signals.domain.types import Role, SECTOR_ETF, Sector, BENCHMARK_SYMBOLS
import pytest

def test_accession_forms():
    assert normalize_accession("000032019324000001") == "0000320193-24-000001"
    assert normalize_accession("0000320193-24-000001") == "0000320193-24-000001"
    assert accession_nodash("0000320193-24-000001") == "000032019324000001"
    with pytest.raises(ValueError):
        normalize_accession("12345")

def test_filing_urls():
    assert filing_txt_url(320193, "0000320193-24-000001") == \
        "https://www.sec.gov/Archives/edgar/data/320193/0000320193-24-000001.txt"
    assert filing_index_url(320193, "0000320193-24-000001") == \
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000001/0000320193-24-000001-index.htm"

def test_owner_group_key():
    assert owner_group_key([1067983, 315090]) == "315090|1067983"
    assert owner_group_key([5, 5]) == "5"
    assert owner_group_ciks("315090|1067983") == [315090, 1067983]
    with pytest.raises(ValueError):
        owner_group_key([])

@pytest.mark.parametrize("title,flags,expected", [
    ("Chief Executive Officer", dict(is_officer=True), [Role.CEO]),
    ("President and CEO", dict(is_officer=True), [Role.CEO, Role.PRESIDENT]),
    ("EVP, CFO", dict(is_officer=True), [Role.CFO]),
    ("Principal Financial Officer", dict(is_officer=True), [Role.CFO]),
    ("Co-CEO", dict(is_officer=True), [Role.CEO]),
    ("Chairman of the Board", dict(is_officer=True, is_director=True), [Role.CHAIR, Role.DIRECTOR]),
    ("SVP, General Counsel", dict(is_officer=True), [Role.GENERAL_COUNSEL]),
    ("COO", dict(is_officer=True), [Role.COO]),
    ("Executive Vice President", dict(is_officer=True), [Role.OTHER_OFFICER]),
    ("Vice Chairman", dict(is_officer=True), [Role.OTHER_OFFICER]),
    ("Chief Accounting Officer", dict(is_officer=True), [Role.OTHER_OFFICER]),
    (None, dict(is_officer=True), [Role.OTHER_OFFICER]),
    (None, dict(is_ten_pct_owner=True), [Role.TEN_PCT_OWNER]),
    (None, dict(is_director=True, is_other=True), [Role.DIRECTOR, Role.OTHER]),
])
def test_normalize_roles(title, flags, expected):
    base = dict(is_director=False, is_officer=False, is_ten_pct_owner=False, is_other=False)
    assert normalize_roles(title, **{**base, **flags}) == expected

def test_top_role_and_constants():
    assert top_role([Role.DIRECTOR, Role.CFO]) == Role.CFO
    assert top_role([]) is None
    assert SECTOR_ETF[Sector("Real Estate")] == "XLRE"
    assert BENCHMARK_SYMBOLS[:2] == ("SPY", "QQQ") and len(BENCHMARK_SYMBOLS) == 13

def test_portfolio_helpers():
    assert effective_n([0.5, 0.5]) == 2.0 and effective_n([1.0]) == 1.0
    assert effective_n([0.25] * 4) == 4.0 and effective_n([2, 2]) == 2.0 and effective_n([]) is None
    assert top5_weight([0.3, 0.2, 0.2, 0.1, 0.1, 0.1]) == pytest.approx(0.9)
    assert [(s["key"], s["weight"]) for s in allocation_slices({"A": 30, "B": 70})] == [("B", 0.7), ("A", 0.3)]
    assert fund_high_conviction([0.06, 0.01, 0.01], ["ADD", "NEW", "ADD"], [60, 50, 1]) == [True, True, False]
```

  Add `from signals.domain.portfolio import effective_n, top5_weight, allocation_slices, fund_high_conviction` to the imports.

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_domain_pure.py`. Expected: FAIL (import errors).

- [ ] **Step 3: Implement.** Role rules are case-insensitive and applied to the title after stripping every `vice[\s-]*(president|chair\w*)` phrase:
  - `CEO`: `\b(ceo|chief executive|principal executive)\b`
  - `CFO`: `\b(cfo|chief financial|principal financial)\b`
  - `COO`: `\b(coo|chief operating)\b`
  - `PRESIDENT`: `\bpresident\b`
  - `CHAIR`: `\bchair(man|woman|person)?\b`
  - `GENERAL_COUNSEL`: `\b(general counsel|chief legal)\b`

  Officer roles come out in ROLE_PRIORITY order. Add `OTHER_OFFICER` when `is_officer` is set and no officer rule matched. Then append `DIRECTOR`, `TEN_PCT_OWNER` and `OTHER` from their flags, in that order.

- [ ] **Step 4:** Run `uv run pytest tests/unit/test_domain_pure.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: domain types, accession, owner group and role helpers`.

---

### Task 3: Calendars (NYSE trading days and SEC business days)

**Files:**
- Create: `backend/src/signals/domain/calendars.py`
- Test: `backend/tests/unit/test_calendars.py`

**Interfaces (produces):** `ET = ZoneInfo("America/New_York")`, plus:
- `now_et() -> datetime` and `to_et(dt: datetime) -> datetime`
- `is_trading_day(d: date) -> bool`
- `next_trading_day(d: date) -> date` (strictly after `d`) and `prev_trading_day(d: date) -> date` (strictly before `d`)
- `add_trading_days(d: date, n: int) -> date`. `d` must be a trading day. The result is the n-th trading day after it.
- `trading_days(start: date, end: date) -> list[date]` (inclusive)
- `trading_days_between(a: date, b: date) -> int`: counts sessions `s` with `a < s <= b`
- `session_open_close(d: date) -> tuple[datetime, datetime]`: ET-aware, reflecting early closes
- `is_sec_business_day(d: date) -> bool`, `add_sec_business_days(d: date, n: int) -> date`, and `sec_business_days_between(a: date, b: date) -> int` (counts `a < d <= b`)

NYSE data comes from `exchange_calendars.get_calendar("XNYS")`, loaded once with `functools.cache`. SEC holidays come from `holidays.country_holidays("US", years=range(2005, 2036))`, the federal list including observed dates.

- [ ] **Step 1: Write the failing tests:**

```python
from datetime import date, time
from signals.domain import calendars as c

def test_good_friday_sec_open_market_closed():
    assert c.is_trading_day(date(2024, 3, 29)) is False
    assert c.is_sec_business_day(date(2024, 3, 29)) is True

def test_columbus_day_market_open_sec_closed():
    assert c.is_trading_day(date(2024, 10, 14)) is True
    assert c.is_sec_business_day(date(2024, 10, 14)) is False

def test_juneteenth_and_observed_july_fourth():
    assert not c.is_trading_day(date(2024, 6, 19)) and not c.is_sec_business_day(date(2024, 6, 19))
    assert c.is_sec_business_day(date(2026, 7, 3)) is False

def test_trading_day_arithmetic():
    assert c.next_trading_day(date(2024, 3, 28)) == date(2024, 4, 1)
    assert c.prev_trading_day(date(2024, 4, 1)) == date(2024, 3, 28)
    assert c.add_trading_days(date(2024, 1, 2), 21) == date(2024, 2, 1)
    assert c.trading_days_between(date(2024, 1, 2), date(2024, 1, 10)) == 6

def test_early_close_day_after_thanksgiving():
    open_, close = c.session_open_close(date(2024, 11, 29))
    assert (open_.time(), close.time()) == (time(9, 30), time(13, 0))
    assert open_.tzinfo is not None

def test_sec_business_day_arithmetic():
    assert c.sec_business_days_between(date(2024, 10, 10), date(2024, 10, 16)) == 3
    assert c.add_sec_business_days(date(2024, 10, 11), 2) == date(2024, 10, 16)
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_calendars.py`. Expected: FAIL.

- [ ] **Step 3:** Implement with the libraries above. `session_open_close` converts the calendar's UTC `session_open` and `session_close` to ET.

- [ ] **Step 4:** Run `uv run pytest tests/unit/test_calendars.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: NYSE and SEC business-day calendars`.

---

### Task 4: Database schema, migration, test database fixtures and factories

**Files:**
- Create:
  - `backend/src/signals/db/{__init__,base,session}.py`
  - `backend/src/signals/db/models/{__init__,reference,filings,insider,funds,prices,derived,app}.py`
  - `backend/alembic.ini`, `backend/migrations/{env.py,script.py.mako}`, `backend/migrations/versions/0001_initial.py`
  - `backend/tests/conftest.py`, `backend/tests/factories.py`
- Test: `backend/tests/integration/test_schema.py`

**Interfaces (produces):**
- `signals.db.base.Base` (a `DeclarativeBase` with the naming convention `ix_%(table_name)s_%(column_0_name)s`, `uq_…`, `fk_…`, `pk_…`)
- `signals.db.session`:
  - `make_engine(url: str) -> Engine` (`pool_pre_ping=True`)
  - `make_session_factory(engine) -> sessionmaker[Session]`
  - `session_scope(factory) -> contextmanager[Session]`, which commits on success and rolls back on error
- ORM classes: `Issuer`, `Ticker`, `TickerEvidence`, `Security`, `FilingAcceptance`, `Owner`, `OwnerRole`, `Filing`, `FilingOwner`, `InsiderTransaction`, `InsiderHolding`, `Form144Notice`, `OwnershipStake`, `FundManager`, `FundFiling`, `FundPosition`, `FundPositionChange`, `PriceDaily`, `Decision`, `DecisionOwner`, `DecisionReturn`, `Position`, `ProfileStats`, `ProfileWindow`, `FundNavDaily`, `FeedItem`, `User`, `Watchlist`, `WatchlistItem`, `JobRequest`, `IngestRun`, `AppState`. All are exported from `signals.db.models`.
- Test fixtures in `tests/conftest.py`: `db_url` (session), `db_engine` (session), `connection`, `session`, `session_factory`, `settings`, `tmp_archive`, `fixture_bytes`, `manifest`, `MockRouter`.
- Factories in `tests/factories.py`. All arguments are keyword-only with defaults, and each factory returns the ORM object:
  - `make_issuer(session, *, cik=1000001, name="Acme Corp", sic=3571, sector="Technology", ticker="ACME", ticker_from=date(2010,1,1), shares_outstanding=1e9)`
  - `make_owner(session, *, cik=2000001, name="Doe Jane", owner_type="person")`
  - `make_filing(session, *, accession_no="0002000001-24-000001", form_type="4", issuer_cik=1000001, primary_cik=2000001, filed_date=date(2024,1,16), accepted_at=datetime(2024,1,16,16,30,tzinfo=ET), owners=(2000001,), source="feed", parse_status="parsed")`. It also inserts `filing_owners` rows.
  - `make_transaction(session, *, accession_no, issuer_cik=1000001, owner_ciks=(2000001,), code="P", transaction_date=date(2024,1,12), shares=1000.0, price=10.0, shares_owned_after=11000.0, plan_10b5_1="none", table_kind="nonderiv", row_no=1, superseded_by=None)`. `acquired_disposed` is `A` for P and `D` for S, and `value_usd = shares*price`.
  - `make_holding(session, *, accession_no, issuer_cik=1000001, owner_ciks=(2000001,), shares_owned=5000.0, row_no=1)`
  - `make_prices(session, symbol: str, start: date, closes: Sequence[float], *, opens=None, adj_factors=None, source="test")`. It writes one row per NYSE trading day from `start`. `open` defaults to `close`, and `adj_close = close * factor` (default 1.0).
  - `make_fund_manager(session, *, cik=3000001, name="Example Capital Management", is_tracked=True)`
  - `make_fund_filing(session, *, accession_no="0003000001-24-000001", filer_cik=3000001, period=date(2024,3,31), filed_date=date(2024,5,15), accepted_at=None, submission_type="13F-HR", amendment_type=None)`. It also creates the `filings` row.
  - `make_fund_position(session, *, accession_no, filer_cik=3000001, period=date(2024,3,31), cusip="000000AA1", shares=100.0, value_usd=1000.0, put_call="", is_effective=True)`
  - `make_security(session, *, cusip="000000AA1", issuer_cik=1000001, ticker="ACME", name="ACME CORP")`
  - `make_decision(session, *, owner_ciks=(2000001,), issuer_cik=1000001, direction="buy", first_trade_date=date(2024,1,12), value_usd=10000.0, shares=1000.0, vwap=10.0, accepted_at=datetime(2024,1,16,16,30,tzinfo=ET), plan_10b5_1="none", badges=())`. It also creates `decision_owners`.
  - `make_decision_return(session, decision_id, *, basis="filed", horizon="6m", raw_return=0.1, excess_spy=0.05, excess_qqq=None, excess_sector=None, is_complete=True)`
  - `make_profile_stats(session, *, kind="insider", cik=2000001, basis="filed", include_10b5_1=False, **metrics)`

**Schema.** Every table has `created_at timestamptz default now()`, and mutable tables also have `updated_at`. Measures are `DOUBLE PRECISION`, CIKs are `BIGINT`, and array columns default to `'{}'`.

```
issuers(cik PK, name NOT NULL, sic INT, sic_description, sector, exchange, state_of_inc, fiscal_year_end,
        shares_outstanding, shares_outstanding_as_of DATE, is_active BOOL DEFAULT true)      GIN trgm(name)
tickers(id BIGSERIAL PK, issuer_cik FK NOT NULL, symbol NOT NULL, valid_from DATE NOT NULL, valid_to DATE,
        source NOT NULL)  UNIQUE(issuer_cik, symbol, valid_from); INDEX(symbol)
ticker_evidence(issuer_cik, symbol, min_seen DATE, max_seen DATE, sources TEXT[])  PK(issuer_cik, symbol)
securities(cusip CHAR(9) PK, issuer_cik, ticker, name, title_of_class, figi, security_type,
           map_source ('openfigi'|'name_match'|'none'), map_status ('pending'|'mapped'|'unresolved'))
           INDEX(issuer_cik), INDEX(ticker)
filing_acceptance(accession_no PK, cik, form_type, filing_date DATE, accepted_at TIMESTAMPTZ NOT NULL)
owners(cik PK, name NOT NULL, owner_type NOT NULL)                                   GIN trgm(name)
owner_roles(owner_cik, issuer_cik, is_director, is_officer, officer_title, roles TEXT[], is_ten_pct_owner,
            is_other, other_text, first_filed DATE, last_filed DATE)  PK(owner_cik, issuer_cik)
filings(accession_no PK, form_type NOT NULL, issuer_cik, primary_cik NOT NULL, filed_date NOT NULL,
        accepted_at, accepted_at_source ('sgml'|'submissions'|'missing'), period_of_report, is_amendment BOOL
        DEFAULT false, amends_accession, original_filed_date DATE, source NOT NULL, raw_path,
        parse_status NOT NULL DEFAULT 'pending',
        parse_error, first_seen_at, parsed_at)
        INDEX(form_type, filed_date), INDEX(issuer_cik), partial INDEX(parse_status) WHERE parse_status<>'parsed'
filing_owners(accession_no FK, owner_cik FK, is_director, is_officer, officer_title, is_ten_pct_owner, is_other)
        PK(accession_no, owner_cik); INDEX(owner_cik)
insider_transactions(id BIGSERIAL PK, accession_no FK NOT NULL, table_kind ('nonderiv'|'deriv'), row_no INT,
        issuer_cik NOT NULL, owner_group NOT NULL, security_title, transaction_date, deemed_execution_date,
        code, form_type, equity_swap BOOL, timeliness, shares, price, value_usd, acquired_disposed,
        shares_owned_after, value_owned_after, direct_indirect, nature_of_ownership,
        plan_10b5_1 NOT NULL DEFAULT 'none', exercise_price, exercise_date, expiration_date,
        underlying_title, underlying_shares, footnotes JSONB DEFAULT '{}', field_footnotes JSONB DEFAULT '{}',
        superseded_by, flags TEXT[])
        UNIQUE(accession_no, table_kind, row_no); INDEX(issuer_cik, transaction_date); INDEX(owner_group);
        INDEX(code, transaction_date)
insider_holdings(id BIGSERIAL PK, accession_no FK, table_kind, row_no, issuer_cik, owner_group, security_title,
        shares_owned, value_owned, direct_indirect, nature_of_ownership, exercise_price, exercise_date,
        expiration_date, underlying_title, underlying_shares, footnotes JSONB, superseded_by)
        UNIQUE(accession_no, table_kind, row_no)
form144_notices(accession_no PK FK, filer_cik, issuer_cik, seller_name, relationship, security_class, broker,
        shares_to_sell, market_value_usd, shares_outstanding, approx_sale_date, exchange, acquired_how,
        acquired_date, plan_10b5_1_adopted DATE, matched_sale_accession)  INDEX(issuer_cik), INDEX(filer_cik)
ownership_stakes(accession_no PK FK, form_type, issuer_cik, cusip, event_date, amendment_no INT, is_activist BOOL,
        percent_of_class, shares, reporting_persons JSONB, group_key, purpose_excerpt, is_current BOOL DEFAULT true)
        INDEX(issuer_cik), INDEX(group_key, issuer_cik)
fund_managers(cik PK, name, is_tracked BOOL DEFAULT false, tracked_reason, latest_period DATE,
        latest_value_usd, latest_positions INT)                                      GIN trgm(name)
fund_filings(accession_no PK FK, filer_cik NOT NULL, period_of_report DATE NOT NULL, filed_date NOT NULL,
        accepted_at, submission_type, report_type, amendment_type, amendment_no INT, value_total_usd,
        entry_total INT, superseded BOOL DEFAULT false)  INDEX(filer_cik, period_of_report)
fund_positions(period DATE, accession_no, cusip CHAR(9), put_call DEFAULT '', filer_cik NOT NULL,
        name_of_issuer, title_of_class, shares, sh_prn, value_usd, is_effective BOOL NOT NULL DEFAULT true)
        PK(period, accession_no, cusip, put_call); PARTITION BY RANGE(period): one partition per year
        2013..2030 plus DEFAULT; INDEX(filer_cik, period); INDEX(cusip, period)
fund_position_changes(filer_cik, period, cusip, put_call, prev_shares, shares, change, shares_change_pct,
        value_usd, weight, prev_weight)  PK(filer_cik, period, cusip, put_call); INDEX(cusip, period)
prices_daily(symbol, date, open, high, low, close, volume, adj_close, source)  PK(symbol, date)
decisions(id BIGSERIAL PK, owner_group, issuer_cik, direction, is_planned BOOL, plan_10b5_1, first_trade_date,
        last_trade_date, shares, value_usd, vwap, stake_change_pct, is_new_position BOOL, sell_fraction,
        first_accession, accessions TEXT[], accepted_at, filed_date, lag_days INT, lag_cost, badges TEXT[])
        INDEX(issuer_cik, first_trade_date); INDEX(owner_group)
decision_owners(decision_id FK ON DELETE CASCADE, owner_cik)  PK(decision_id, owner_cik); INDEX(owner_cik)
decision_returns(decision_id FK ON DELETE CASCADE, basis, horizon, entry_date, entry_price_adj, entry_kind,
        exit_date, raw_return, excess_spy, excess_qqq, excess_sector, is_complete BOOL, exit_reason, flags TEXT[])
        PK(decision_id, basis, horizon)
positions(owner_cik, issuer_cik, security_title, direct_indirect, shares, as_of_date, last_accession)
        PK(owner_cik, issuer_cik, security_title, direct_indirect)
profile_stats(kind, cik, basis, include_10b5_1 BOOL, n_decisions INT, n_buys INT, n_sells INT, n_complete INT,
        avg_roi_6m, avg_roi_6m_raw, median_6m, hit_rate, best_decision_id, worst_decision_id, avg_lag_days,
        avg_lag_cost, shrunk_mean, rating INT, confidence, risk_label, primary_issuer_cik, sector,
        last_trade_date)  PK(kind, cik, basis, include_10b5_1)
profile_windows(kind, cik, basis, include_10b5_1, window, start_date, end_date, ret, ret_spy, ret_qqq,
        ret_sector, annualized, vol, max_drawdown, beta, time_invested_pct)
        PK(kind, cik, basis, include_10b5_1, window)
fund_nav_daily(cik, basis, date, nav, nav_spy, nav_qqq, nav_sector, coverage)  PK(cik, basis, date)
feed_items(accession_no PK FK, accepted_at, filed_date, form_type, issuer_cik, issuer_name, ticker, owner_group,
        owner_ciks BIGINT[], owner_names, top_role, direction, codes TEXT[], value_usd, shares, price,
        plan_10b5_1, badges TEXT[], market_cap_usd, sector, summary, lag_days INT, first_trade_date)
        INDEX(accepted_at DESC); INDEX(issuer_cik, accepted_at); INDEX(filed_date)
users(id SERIAL PK, name)            -- migration seeds (1, 'me')
watchlists(id SERIAL PK, user_id FK, name)  UNIQUE(user_id, name)
watchlist_items(watchlist_id FK ON DELETE CASCADE, kind, cik, added_at)  PK(watchlist_id, kind, cik)
job_requests(id BIGSERIAL PK, kind, params JSONB, status, progress JSONB DEFAULT '{}', error, requested_at,
        started_at, finished_at)  INDEX(status, requested_at)
ingest_runs(id BIGSERIAL PK, job, started_at, finished_at, fetched INT, new_rows INT, missed INT, errors INT,
        notes JSONB)  INDEX(job, started_at DESC)
app_state(key PK, value JSONB, updated_at)
```

**How the test database works.** `db_url` creates the database `signals_test_<uuid8>` through an AUTOCOMMIT connection to the `postgres` database. The admin URL comes from env `SIGNALS_TEST_ADMIN_URL` (default `postgresql+psycopg://signals:signals@127.0.0.1:5432/postgres`). It then runs `alembic upgrade head` programmatically, yields the URL, and at teardown runs `DROP DATABASE … WITH (FORCE)`.

`connection` opens a connection and begins a transaction. `session` is `Session(bind=connection, join_transaction_mode="create_savepoint")`. `session_factory` returns sessions bound the same way. `settings` is `Settings(sec_user_agent="Signals Test test@example.com", database_url=db_url, raw_archive_dir=tmp_path/"raw", _env_file=None)`.

`MockRouter(routes: Mapping[str, bytes | int | tuple[int, bytes] | Callable[[httpx.Request], httpx.Response]])` provides `.transport` (an `httpx.MockTransport`), `.client` (an `httpx.Client`) and `.requests` (the list of every request seen). Routes match the full URL first, then the URL without its query string. An unmatched URL returns 404.

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_schema.py`:

```python
from sqlalchemy import inspect, text
from tests.factories import make_issuer, make_owner, make_filing, make_transaction

EXPECTED = {"issuers","tickers","ticker_evidence","securities","filing_acceptance","owners","owner_roles",
  "filings","filing_owners","insider_transactions","insider_holdings","form144_notices","ownership_stakes",
  "fund_managers","fund_filings","fund_positions","fund_position_changes","prices_daily","decisions",
  "decision_owners","decision_returns","positions","profile_stats","profile_windows","fund_nav_daily",
  "feed_items","users","watchlists","watchlist_items","job_requests","ingest_runs","app_state"}

def test_all_tables_exist(db_engine):
    assert EXPECTED <= set(inspect(db_engine).get_table_names())

def test_fund_positions_partitioned(session):
    n = session.execute(text("select count(*) from pg_inherits i join pg_class p on p.oid=i.inhparent "
                             "where p.relname='fund_positions'")).scalar_one()
    assert n >= 19   # 2013..2030 + default

def test_pg_trgm_and_default_user(session):
    assert session.execute(text("select 1 from pg_extension where extname='pg_trgm'")).scalar_one() == 1
    assert session.execute(text("select name from users where id=1")).scalar_one() == "me"

def test_factories_roundtrip(session):
    make_issuer(session); make_owner(session)
    f = make_filing(session)
    t = make_transaction(session, accession_no=f.accession_no)
    assert (t.value_usd, t.acquired_disposed, t.owner_group) == (10000.0, "A", "2000001")
```

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_schema.py`. Expected: FAIL (the fixtures and models don't exist yet).

- [ ] **Step 3: Implement** the models (split by area, as listed), `db/session.py`, `conftest.py` and `factories.py`.

- [ ] **Step 4: Generate the migration.**
  - Run `uv run alembic revision --autogenerate -m initial --rev-id 0001_initial` against a scratch database.
  - Hand-edit it: add `CREATE EXTENSION IF NOT EXISTS pg_trgm` first; declare `fund_positions` with `postgresql_partition_by='RANGE (period)'`; then create partitions `fund_positions_y2013` … `fund_positions_y2030` (`FOR VALUES FROM ('YYYY-01-01') TO ('YYYY+1-01-01')`) and `fund_positions_default`; add the GIN trgm indexes (`gin_trgm_ops`); and seed `users (1, 'me')`.
  - `downgrade()` drops everything.

- [ ] **Step 5:** Run `uv run pytest -q`. Expected: all pass. Also run `uv run alembic upgrade head` against the dev database (`signals`) and expect `Running upgrade -> 0001_initial`.

- [ ] **Step 6: Commit** with message `feat: database schema, initial migration, test fixtures and factories`.

---

### Task 5: Database-backed domain helpers (tickers, feed items, app state)

**Files:**
- Create: `backend/src/signals/domain/{tickers,feed,appstate}.py`
- Test: `backend/tests/integration/test_domain_db.py`

**Interfaces (produces):**
- `canonical_symbol(raw: str | None) -> str | None`:
  - Upper-case the value, strip it, remove inner spaces and replace `-` with `.`.
  - Return `None` for empty input, for `NONE`, `N/A` and `NA`, and for anything not matching `^[A-Z][A-Z0-9.]{0,9}$`.
- `record_ticker_evidence(session, issuer_cik: int, raw_symbol: str | None, seen_on: date, source: str) -> str | None`: upserts `ticker_evidence`, updating min/max seen and merging sources. Returns the canonical symbol, or `None` when the symbol is rejected.
- `rebuild_tickers(session, issuer_ciks: Collection[int] | None = None) -> int`:
  - For each issuer, order its evidence symbols by `min_seen`.
  - Each symbol's `valid_from` is its `min_seen`. The first symbol's `valid_from` becomes `date(1990, 1, 1)` so older history resolves.
  - `valid_to` is the next symbol's `min_seen - 1 day`. The last symbol is open-ended.
  - Replaces that issuer's `tickers` rows.
- `TickerInterval(symbol: str, valid_from: date, valid_to: date | None)` and `ticker_intervals(session, issuer_cik) -> list[TickerInterval]`
- `resolve_symbol(session, issuer_cik, on: date) -> str | None` and `current_symbol(session, issuer_cik) -> str | None`
- `issuer_for_symbol(session, symbol: str, on: date | None = None) -> int | None`: with `on=None`, it returns the issuer whose interval for that symbol is open, or else the one with the latest `valid_to`.
- `FeedItemIn`: a dataclass with the same fields as `feed_items`. `upsert_feed_item(session, item: FeedItemIn) -> None` upserts on `accession_no`.
- `summarize_trade(direction: str, shares: float | None, price: float | None, value: float | None) -> str`: for example `"Bought 12,000 sh @ $41.25 ($495,000)"` or `"Sold 5,000 sh @ $10.00 ($50,000)"`. A missing piece is left out.
- `get_state(session, key) -> dict | None` and `set_state(session, key, value: dict) -> None`

- [ ] **Step 1: Write the failing tests:**

```python
from datetime import date
from signals.domain.tickers import (canonical_symbol, record_ticker_evidence, rebuild_tickers,
    resolve_symbol, current_symbol, issuer_for_symbol)
from signals.domain.feed import FeedItemIn, upsert_feed_item, summarize_trade
from signals.domain.appstate import get_state, set_state
from tests.factories import make_issuer

def test_canonical_symbol():
    assert canonical_symbol("brk-b") == "BRK.B"
    assert canonical_symbol(" aapl ") == "AAPL"
    assert canonical_symbol("NONE") is None and canonical_symbol("common stock") is None

def test_ticker_change_intervals(session):
    make_issuer(session, cik=1000002, name="Globex Inc", ticker="GBX", ticker_from=date(2016, 1, 5))
    record_ticker_evidence(session, 1000002, "GBX", date(2016, 1, 5), "form4")
    record_ticker_evidence(session, 1000002, "GLBX", date(2022, 6, 10), "form4")
    record_ticker_evidence(session, 1000002, "GBX", date(2021, 3, 1), "form4")   # out of order
    rebuild_tickers(session, [1000002])
    assert resolve_symbol(session, 1000002, date(2020, 1, 1)) == "GBX"
    assert resolve_symbol(session, 1000002, date(2023, 1, 1)) == "GLBX"
    assert current_symbol(session, 1000002) == "GLBX"
    assert issuer_for_symbol(session, "GBX", date(2020, 1, 1)) == 1000002

def test_reused_ticker_resolves_by_date(session):
    make_issuer(session, cik=1000003, name="Old Co", ticker="XYZ", ticker_from=date(2016, 1, 1))
    make_issuer(session, cik=1000004, name="New Co", ticker="NEWC", ticker_from=date(2016, 1, 1))
    record_ticker_evidence(session, 1000003, "XYZ", date(2016, 2, 1), "form4")
    record_ticker_evidence(session, 1000003, "XYZA", date(2019, 1, 1), "form4")
    record_ticker_evidence(session, 1000004, "XYZ", date(2020, 5, 1), "form4")
    rebuild_tickers(session, [1000003, 1000004])
    assert issuer_for_symbol(session, "XYZ", date(2017, 1, 1)) == 1000003
    assert issuer_for_symbol(session, "XYZ") == 1000004

def test_feed_upsert_and_state(session):
    item = FeedItemIn(accession_no="0002000001-24-000001", form_type="4", summary="x")  # other fields default None/()
    upsert_feed_item(session, item); upsert_feed_item(session, FeedItemIn(**{**item.__dict__, "summary": "y"}))
    assert session.execute(text("select summary from feed_items")).scalars().all() == ["y"]
    set_state(session, "live_poll", {"ok": True}); assert get_state(session, "live_poll") == {"ok": True}

def test_summarize_trade():
    assert summarize_trade("buy", 12000, 41.25, 495000) == "Bought 12,000 sh @ $41.25 ($495,000)"
    assert summarize_trade("sell", 5000, None, None) == "Sold 5,000 sh"
```

  Add `from sqlalchemy import text` to the imports. `FeedItemIn` fields default to `None` or empty tuples, so partial construction works.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_domain_db.py`. Expected: FAIL.

- [ ] **Step 3:** Implement per the interfaces.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_domain_db.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: dated tickers, feed item upsert and app state helpers`.

---

### Task 6: SEC client (rate limiter, raw archive, HTTP client)

**Files:**
- Create: `backend/src/signals/sec/{__init__,ratelimit,archive,client}.py`, `backend/src/signals/logging.py`
- Test: `backend/tests/unit/test_sec_client.py`

**Interfaces (produces):**
- `Priority` enum: `LIVE`, `BULK`
- `TokenBucket(rate: float, capacity: int, *, reserve_for_live: int = 1, clock=time.monotonic, sleep=time.sleep)` with `.acquire(priority: Priority = Priority.BULK) -> None`.
  - It's thread-safe (`threading.Lock`). Tokens refill continuously.
  - `LIVE` needs at least 1 token. `BULK` needs at least `1 + reserve_for_live`, so live polling always finds a token.
  - When there aren't enough tokens, it sleeps outside the lock for the computed wait and retries.
- `RawArchive(root: Path)`:
  - `.put(kind: str, key: str, data: bytes, ext: str = "txt") -> Path` writes gzip to `<root>/<kind>/<sha1(key)[:2]>/<key>.<ext>.gz` atomically (temp file, then `os.replace`).
  - `.get(kind, key, ext="txt") -> bytes`, `.exists(kind, key, ext="txt") -> bool`, and `.read_path(path: Path) -> bytes`.
- Errors: `SecError` is the base class. `SecNotFoundError(url)`, `SecHttpError(url, status)` and `SecBlockedError(until: datetime)` extend it.
- `SecClient(settings, *, http: httpx.Client | None = None, limiter: TokenBucket | None = None, archive: RawArchive | None = None, clock=now_et, sleep=time.sleep, rand=random.random, on_block: Callable[[datetime], None] | None = None)`:
  - `.get(url: str, *, priority: Priority = Priority.BULK, archive_as: tuple[str, str, str] | None = None) -> bytes`
  - `.get_filing_txt(cik: int, accession: str, *, priority=Priority.BULK) -> bytes`, which archives as `("filing", accession, "txt")`
  - `.download(url: str, dest: Path, *, priority=Priority.BULK) -> Path`: streams the body (`httpx.Client.stream`) to `dest.with_suffix(dest.suffix + ".part")`, then `os.replace`s it onto `dest`. It uses the same retry and 403 rules as `.get`, and is meant for multi-GB files such as `submissions.zip`.
  - `.blocked_until: datetime | None`
  - Retries: on timeout, 429 or 5xx, up to 5 retries, sleeping `min(30, 2**(attempt-1)) + rand()*0.5` seconds. On 404 it raises `SecNotFoundError`. On 403 it sets `blocked_until = clock() + 10 min`, calls `on_block`, and raises `SecBlockedError`. While `clock() < blocked_until`, it raises `SecBlockedError` without sending any request. Timeouts are `httpx.Timeout(30, connect=5)`.
- `build_sec_client(settings, *, archive: RawArchive, on_block=None) -> SecClient` builds it with `TokenBucket(rate=settings.sec_rate_limit, capacity=int(settings.sec_rate_limit))`.
- `signals.logging.configure_logging(json: bool = True) -> None` and `get_logger(name: str)`, using structlog.

- [ ] **Step 1: Write the failing tests** with a fake clock. The `FakeClock` has `.now` (a datetime), `.mono` (a float), and a `.sleep(s)` that advances both.

```python
def test_bucket_bursts_then_waits(fake_clock):
    b = TokenBucket(rate=8, capacity=8, clock=fake_clock.monotonic, sleep=fake_clock.sleep, reserve_for_live=0)
    for _ in range(8): b.acquire()
    assert fake_clock.slept == []
    b.acquire(); assert fake_clock.slept == [pytest.approx(0.125)]

def test_bulk_leaves_reserve_for_live(fake_clock):
    b = TokenBucket(rate=8, capacity=2, clock=fake_clock.monotonic, sleep=fake_clock.sleep, reserve_for_live=1)
    b.acquire(Priority.BULK)                      # 2 -> 1 token
    b.acquire(Priority.LIVE); assert fake_clock.slept == []   # live may take the last token
    b.acquire(Priority.BULK); assert fake_clock.slept           # bulk had to wait

def test_sends_user_agent_and_archives(settings, tmp_path):
    r = MockRouter({"https://www.sec.gov/x": b"hello"})
    c = SecClient(settings, http=r.client, archive=RawArchive(tmp_path), sleep=lambda s: None)
    assert c.get("https://www.sec.gov/x", archive_as=("filing", "k", "txt")) == b"hello"
    assert r.requests[0].headers["User-Agent"] == settings.sec_user_agent
    assert RawArchive(tmp_path).get("filing", "k") == b"hello"

def test_retries_429_with_backoff(settings):
    seq = iter([429, 429, 200]); slept = []
    r = MockRouter({"https://www.sec.gov/y": lambda req: httpx.Response(next(seq), content=b"ok")})
    c = SecClient(settings, http=r.client, sleep=slept.append, rand=lambda: 0.0)
    assert c.get("https://www.sec.gov/y") == b"ok" and slept == [1.0, 2.0]

def test_gives_up_after_five_retries(settings):
    r = MockRouter({"https://www.sec.gov/z": 503})
    c = SecClient(settings, http=r.client, sleep=lambda s: None, rand=lambda: 0.0)
    with pytest.raises(SecHttpError): c.get("https://www.sec.gov/z")
    assert len(r.requests) == 6

def test_404_and_403_pause(settings, fake_clock):
    r = MockRouter({"https://www.sec.gov/nf": 404, "https://www.sec.gov/blocked": 403})
    blocked = []
    c = SecClient(settings, http=r.client, clock=fake_clock.now_et, sleep=fake_clock.sleep, on_block=blocked.append)
    with pytest.raises(SecNotFoundError): c.get("https://www.sec.gov/nf")
    with pytest.raises(SecBlockedError): c.get("https://www.sec.gov/blocked")
    assert c.blocked_until == fake_clock.now_et() + timedelta(minutes=10) and blocked
    with pytest.raises(SecBlockedError): c.get("https://www.sec.gov/nf")
    assert len(r.requests) == 2      # nothing sent while blocked

def test_download_streams_to_file(settings, tmp_path):
    r = MockRouter({"https://www.sec.gov/big.zip": b"x" * 100_000})
    c = SecClient(settings, http=r.client, sleep=lambda s: None)
    out = c.download("https://www.sec.gov/big.zip", tmp_path / "big.zip")
    assert out.read_bytes() == b"x" * 100_000 and not (tmp_path / "big.zip.part").exists()
```

  `fake_clock` is a fixture in `tests/conftest.py`. The first tests pass an explicit high-rate limiter where needed.

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_sec_client.py`. Expected: FAIL.

- [ ] **Step 3:** Implement per the interfaces.

- [ ] **Step 4:** Run `uv run pytest tests/unit/test_sec_client.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: rate-limited SEC client with raw archive`.

---

### Task 7: Record real fixtures, and the curated fund list

**Files:**
- Create: `scripts/record_fixtures.py`, `backend/tests/fixtures/sec/MANIFEST.json`, the files under `backend/tests/fixtures/sec/**`, and `backend/src/signals/reference/tracked_funds.csv`
- Test: `backend/tests/unit/test_fixtures_manifest.py`

**Interfaces (produces):**
- `tests/fixtures/sec/MANIFEST.json`: `{ "<key>": {"file": "<relative path>", "source_url": "...", "why": "...", "accession": "...", "cik": 0, "form_type": "...", "filed_date": "YYYY-MM-DD", "accepted_at": "YYYY-MM-DDTHH:MM:SS-05:00", "expect": {...}} }`
- Every `expect` anchor is read by a person from the filing's sec.gov HTML view. That keeps anchors independent of our parsers.
- The fixture `manifest` in `tests/conftest.py` loads it, and `fixture_bytes(key)` returns the file's bytes.
- `reference/tracked_funds.csv` has columns `cik,name,reason`, with `reason` = `curated`.

**Fixture set.** `record_fixtures.py` saves filing `.txt` files under `filings/`. It uses `SecClient` with the real `.env` settings; this is the only task allowed to use the network.

| Key | What to find | `expect` anchors |
|---|---|---|
| `form4_buy_single` | Form 4, one reporting owner, at least one `P` row | `issuer_cik, owner_ciks, n_nonderiv_trans, codes, first_nonderiv{transaction_date,shares,price,shares_owned_after}, aff10b5one` |
| `form4_joint` | Form 4 with at least 2 reporting owners (for example Berkshire Hathaway plus Buffett in an OXY purchase) | the same, plus `owner_ciks` of length ≥ 2 |
| `form4a_original`, `form4a_amendment` | A Form 4/A and the original it amends (use `dateOfOriginalSubmission` and the owner's submissions list) | `date_of_original_submission`, `codes` |
| `form4_10b5_1_flag` | Form 4 filed after 2023-04-01 with `aff10b5One` = 1 and `S` rows | `aff10b5one: true`, `codes` |
| `form4_10b5_1_footnote` | 2021–2022 Form 4 `S` with "10b5-1" in a footnote | `footnote_ids_with_10b5_1` |
| `form4_exercise_sale` | Form 4 with a derivative `M` and a same-day nonderivative `S` | `n_deriv_trans`, `codes` |
| `form4_footnote_price` | A row whose price is only a `footnoteId`. If none turns up in 30 minutes, make a copy of `form4_buy_single` with the price edited and label it `"synthetic": true` | `row_no`, `price: null` |
| `form4_value_owned` | A row using `valueOwnedFollowingTransaction`. May be synthetic, as above | `value_owned_after` |
| `form3`, `form5` | Any, with holdings | `n_nonderiv_holdings` |
| `form144` | Any Form 144 (XML) | `issuer_cik, shares_to_sell, market_value_usd, approx_sale_date` |
| `f13f_small` | 13F-HR filed after 2023-01-03 with 20–60 rows (for example Berkshire, CIK 1067983) | `period_of_report, table_entry_total, table_value_total, n_rows` |
| `f13f_pre2023` | 13F-HR filed before 2023-01-03 (values in thousands) | the same, plus `first_row{cusip,value_reported}` |
| `f13f_restatement` | 13F-HR/A with `amendmentType` RESTATEMENT | `amendment_type` |
| `sc13d`, `sc13g` | SCHEDULE 13D and SCHEDULE 13G, XML, filed after 2024-12-18 | `issuer_cik, cusip, n_persons, max_percent_of_class` |
| `atom_form4_p1`, `atom_form4_p2` | `getcurrent` Atom feed for type=4, start=0 and start=100 | `n_entries, first{accession,form_type,cik}` |
| `atom_form4_424b2` | A feed page containing a `424B2` entry (from type=4 or type=424) | `n_424b2` |
| `daily_index` | `form.<YYYYMMDD>.idx` of a recent business day, trimmed to the header plus 400 lines, keeping one line whose form type has spaces | `n_entries, sample{form_type,cik,date_filed,accession}` |
| `full_index` | `full-index/2025/QTR1/form.idx`, trimmed to the header plus the 144, SCHEDULE 13D and 13F-HR lines (up to 300) | `n_entries` |
| `bulk_345_slice` | A zip built from `2025q1_form345.zip`: 50 accessions including a joint filing, a 4/A and a 10b5-1 footnote, with every table filtered and headers kept | `accessions, n_nonderiv_trans, n_nonderiv_holding, n_deriv_trans, n_deriv_holding, joint_accession, amendment_accession, footnote_10b5_1_accession` |
| `bulk_13f_slice_2022`, `bulk_13f_slice_2025` | 10 accessions each from a quarterly set of 2022 and the latest 3-month set. The 2025 slice includes one RESTATEMENT | `accessions, n_infotable, restatement_accession, sample{accession,cusip,value_reported}` |
| `listing_345_html`, `listing_13f_html` | The two data set listing pages | `n_links` |
| `submissions_owner` | `data.sec.gov/submissions/CIK##########.json` for `form4_buy_single`'s owner | `accession`, `acceptanceDateTime` (the raw string) |
| `company_tickers_exchange` | Trimmed to 200 entries plus every fixture issuer | `n_entries` |
| `frames_sample` | The latest `EntityCommonStockSharesOutstanding` frame, trimmed to 50 entries | `n_entries, sample{cik,val,end}` |
| `alpaca_raw_p1/p2`, `alpaca_all_p1/p2` | SPY and AAPL daily bars from 2016-01-04 to 2016-02-29 with `limit=40`, so it paginates, for `adjustment=raw` and `adjustment=all` | `symbols, n_bars{SPY,AAPL}` |
| `openfigi_sample` | A POST mapping for `037833100`, `084670702` and `000000000` | `tickers{037833100:"AAPL"}` plus one `warning` |

**Curated funds.** Resolve each name to its 13F filer CIK through EDGAR company search, and keep only verified CIKs (at least 40):

Berkshire Hathaway; Pershing Square Capital Management; Scion Asset Management; Appaloosa; Baupost Group; Greenlight Capital; Third Point; Tiger Global Management; Coatue Management; Duquesne Family Office; Viking Global Investors; Lone Pine Capital; Icahn Carl C; ValueAct Holdings; Elliott Investment Management; Soros Fund Management; Bridgewater Associates; Renaissance Technologies; Citadel Advisors; Himalaya Capital Management; Akre Capital Management; Fairholme Capital Management; Oaktree Capital Management; Paulson & Co; Maverick Capital; Glenview Capital Management; Jana Partners; Starboard Value; Trian Fund Management; Tweedy Browne; Ruane Cunniff & Goldfarb; Gates Foundation Trust; Dalal Street (Pabrai); Fundsmith; Polen Capital Management; Gardner Russo & Quinn; Davis Selected Advisers; First Eagle Investment Management; Egerton Capital; D1 Capital Partners; Whale Rock Capital; Durable Capital Partners; ARK Investment Management; Pzena Investment Management; Markel Group; Harris Associates; Dodge & Cox; Point72 Asset Management; Two Sigma Investments; Brave Warrior Advisors.

- [ ] **Step 1: Write the failing test** `test_fixtures_manifest.py`:

```python
REQUIRED = ["form4_buy_single","form4_joint","form4a_original","form4a_amendment","form4_10b5_1_flag",
  "form4_10b5_1_footnote","form4_exercise_sale","form4_footnote_price","form4_value_owned","form3","form5",
  "form144","f13f_small","f13f_pre2023","f13f_restatement","sc13d","sc13g","atom_form4_p1","atom_form4_p2",
  "atom_form4_424b2","daily_index","full_index","bulk_345_slice","bulk_13f_slice_2022","bulk_13f_slice_2025",
  "listing_345_html","listing_13f_html","submissions_owner","company_tickers_exchange","frames_sample",
  "alpaca_raw_p1","alpaca_raw_p2","alpaca_all_p1","alpaca_all_p2","openfigi_sample"]

def test_manifest_complete(manifest):
    missing = [k for k in REQUIRED if k not in manifest]
    assert not missing
    for k in REQUIRED:
        assert fixture_path(manifest[k]["file"]).exists(), k
        assert manifest[k]["expect"], k

def test_tracked_funds_csv():
    rows = list(csv.DictReader(open(TRACKED_CSV)))
    assert len(rows) >= 40 and all(r["cik"].isdigit() and r["reason"] == "curated" for r in rows)
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_fixtures_manifest.py`. Expected: FAIL.

- [ ] **Step 3: Write `scripts/record_fixtures.py`** with Typer subcommands:
  - `filing KEY CIK ACCESSION`
  - `url KEY URL PATH`
  - `slice-345 KEY SRC_ZIP ACCESSIONS…`
  - `slice-13f KEY SRC_ZIP ACCESSIONS…`
  - `alpaca`
  - `openfigi`
  - `manifest-set KEY --json '{…}'`

  Each subcommand writes the file and merges its entry into MANIFEST.json. Large source ZIPs are downloaded to `data/tmp/`, which is not committed.

- [ ] **Step 4: Find and record every fixture** in the table, reading each `expect` anchor from the filing's sec.gov page. Write `tracked_funds.csv`.

- [ ] **Step 5:** Run `uv run pytest tests/unit/test_fixtures_manifest.py`. Expected: pass. Then run `du -sh backend/tests/fixtures`. Expected: under 25 MB. Trim anything larger.

- [ ] **Step 6: Commit** with message `test: recorded SEC, Alpaca and OpenFIGI fixtures with manifest; curated fund list`.

---

### Task 8: SGML filing reader and XML helpers

**Files:**
- Create: `backend/src/signals/sec/sgml.py`, `backend/src/signals/ingest/__init__.py`, `ingest/parsers/__init__.py`, `ingest/parsers/xmlutil.py`
- Test: `backend/tests/unit/test_sgml.py`, `backend/tests/unit/test_xmlutil.py`

**Interfaces (produces):**
- `SgmlDocument(type: str, sequence: int, filename: str | None, description: str | None, body: bytes)`, with `.xml() -> bytes | None` returning the bytes between `<XML>` and `</XML>`, stripped.
- `SgmlFiling`, a frozen dataclass with:
  - `accession_no: str`, `form_type: str`, `filed_date: date`
  - `accepted_at: datetime | None`: `<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS`, interpreted as ET, tz-aware
  - `period_of_report: date | None`
  - `ciks_by_role: dict[str, list[int]]`: keys exactly as in the header, such as `"REPORTING-OWNER"`, `"ISSUER"`, `"FILER"`, `"SUBJECT COMPANY"`, `"FILED BY"`
  - `names_by_cik: dict[int, str]`
  - `documents: list[SgmlDocument]`
  - Methods: `.from_txt(data: bytes) -> SgmlFiling` (classmethod), `.xml_documents() -> list[SgmlDocument]`, `.primary_cik() -> int`, whose preference order is REPORTING-OWNER, FILER, FILED BY, ISSUER, SUBJECT COMPANY.
- `xmlutil`:
  - `parse_xml(data: bytes) -> etree._Element`: lxml with `recover=False`, `resolve_entities=False`, `no_network=True`, and namespaces stripped from tags.
  - `FieldValue(value: str | None, footnote_ids: tuple[str, ...])`
  - `field(el, path: str) -> FieldValue`: reads `path/value` text, or `path` text when there's no `<value>` child, and collects `footnoteId/@id` under the path.
  - `text(el, path) -> str | None`
  - `to_bool(s) -> bool | None`: `1/true/yes` → True, `0/false/no` → False
  - `to_float(s) -> float | None`: strips `,` and `$`
  - `to_date(s) -> date | None`: accepts `YYYY-MM-DD`, `YYYY-MM-DD±hh:mm`, `MM-DD-YYYY`, `MM/DD/YYYY` and `DD-MON-YYYY`

- [ ] **Step 1: Write the failing tests.**
  - For each filing fixture in the manifest, `SgmlFiling.from_txt(bytes)` matches the manifest's `accession`, `form_type`, `filed_date` and `accepted_at`.
  - `form4_joint` has at least 2 CIKs under `REPORTING-OWNER`.
  - `f13f_small` has 2 XML documents, and their types include `"INFORMATION TABLE"`.
  - `sc13d` has an XML document of type `"SCHEDULE 13D"`.
  - DST: when the `accepted_at` month is between April and October, `utcoffset() == timedelta(hours=-4)`.
  - xmlutil tests with inline XML:

```python
def test_field_value_and_footnote():
    el = parse_xml(b'<r><p><value>10.5</value><footnoteId id="F1"/></p><q><footnoteId id="F2"/></q></r>')
    assert field(el, "p") == FieldValue("10.5", ("F1",)); assert field(el, "q") == FieldValue(None, ("F2",))

def test_conversions():
    assert to_bool("1") is True and to_bool("false") is False and to_bool(None) is None
    assert to_float("1,234.50") == 1234.5 and to_float("") is None
    assert to_date("2024-01-15-05:00") == date(2024, 1, 15) and to_date("15-JAN-2024") == date(2024, 1, 15)
    assert to_date("03-31-2024") == date(2024, 3, 31)

def test_namespaces_stripped():
    el = parse_xml(b'<ns1:informationTable xmlns:ns1="http://x"><ns1:infoTable/></ns1:informationTable>')
    assert el.tag == "informationTable" and el[0].tag == "infoTable"
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_sgml.py tests/unit/test_xmlutil.py`. Expected: FAIL.

- [ ] **Step 3:** Implement. The header is everything before `</SEC-HEADER>`. Role blocks start at unindented lines ending in `:` and hold `CENTRAL INDEX KEY:` and `COMPANY CONFORMED NAME:` lines. Documents are split on `<DOCUMENT>`.

- [ ] **Step 4:** Run `uv run pytest tests/unit/test_sgml.py tests/unit/test_xmlutil.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: SGML filing reader and XML helpers`.

---

### Task 9: Ingest pipeline and handler registry

**Files:**
- Create:
  - `backend/src/signals/ingest/dispatch.py`, `ingest/pipeline.py`
  - `ingest/handlers/__init__.py`, which imports `.insider` and `.funds`
  - Stubs: `ingest/handlers/insider.py` (A), `ingest/handlers/funds.py` (B)
- Test: `backend/tests/integration/test_pipeline.py`

**Interfaces (produces):**
- `HandlerContext(settings: Settings, archive: RawArchive, source: str, now: datetime)`
- `Handler = Callable[[Session, SgmlFiling, Filing, HandlerContext], None]`
- `register_handler(form_types: Iterable[str], handler: Handler) -> None`
- `get_handler(form_type: str) -> Handler | None`
- `registered_forms() -> frozenset[str]`
- `reset_registry() -> None` (for tests only)
- `IngestOutcome(accession_no: str, status: Literal["parsed","error","skipped","duplicate"], error: str | None = None)`
- `ingest_accession(client: SecClient, session: Session, *, cik: int, accession: str, source: str, priority: Priority = Priority.BULK, first_seen_at: datetime | None = None, settings: Settings, archive: RawArchive) -> IngestOutcome`
  - If `filings.parse_status == 'parsed'`, return `duplicate` without any HTTP call.
  - Otherwise fetch the `.txt`, archive it, and call `ingest_raw`.
- `ingest_raw(session, raw: bytes, *, source: str, raw_path: str | None, first_seen_at: datetime | None, settings, archive) -> IngestOutcome`:
  - Upsert `filings` from `SgmlFiling`: form type, `filed_date`, `accepted_at` (`accepted_at_source='sgml'`), period, `primary_cik`, the issuer CIK (from ISSUER or SUBJECT COMPANY when present), `is_amendment = form_type.endswith("/A")` and `first_seen_at`, with status `pending`.
  - Then run the handler inside `session.begin_nested()`.
  - Success sets `parsed` and `parsed_at`. An exception rolls back the savepoint and sets `error` with `f"{type(e).__name__}: {e}"`. No handler sets `skipped`.
  - It commits nothing. The caller owns the transaction.
- `reparse_accession(session, accession: str, *, settings, archive) -> IngestOutcome`: reads the raw archive, with no network.

- [ ] **Step 1: Write the failing tests** (using the `form4_buy_single` fixture):
  - `test_ingest_raw_runs_registered_handler`: `reset_registry()`, then register a handler for `"4"` that inserts an `Owner`. Result: status `parsed`, the filings row has the manifest `accepted_at`, and the owner exists.
  - `test_handler_error_rolls_back_and_records`: the handler inserts an owner and then raises `ValueError("boom")`. Result: status `error`, `parse_error == "ValueError: boom"`, and the owner is gone.
  - `test_unknown_form_skipped`: with an empty registry, the status is `skipped`.
  - `test_ingest_accession_duplicate_makes_no_request`: pre-insert a parsed filing. The MockRouter records zero requests and the status is `duplicate`.
  - `test_ingest_accession_fetches_and_archives`: the MockRouter serves the fixture at `filing_txt_url`. The archive has the key, and `filings.raw_path` is set.
  - `test_reparse_uses_archive`: after an error, re-register a working handler, call `reparse_accession`, and the status is `parsed`.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_pipeline.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_pipeline.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: ingest pipeline with handler registry, savepoints and reparse`.

---

### Task 10: Jobs, worker, CLI, and the backfill orchestrator

**Files:**
- Create:
  - `backend/src/signals/jobs.py`, `backend/src/signals/worker.py`, `backend/src/signals/cli.py`
  - Stubs: `ingest/jobs_insider.py` (A), `ingest/jobs_funds.py` (B), `reference/__init__.py`, `reference/jobs.py` (C), `prices/__init__.py`, `prices/jobs.py` (C), `analytics/__init__.py`, `analytics/jobs.py` (D)
- Test: `backend/tests/integration/test_jobs.py`, `backend/tests/unit/test_cli.py`

**Interfaces (produces):**
- `JobContext(settings, session_factory: Callable[[], Session], sec: SecClient, archive: RawArchive, request_id: int | None, params: dict, progress: dict, save_progress: Callable[[dict], None], now: Callable[[], datetime])`
- `JobSpec(kind: str, func: Callable[[JobContext], dict | None], cron: dict | None, interval_seconds: int | None)`
- `register_job(kind: str, *, cron: dict | None = None, interval_seconds: int | None = None)` is a decorator that adds to `JOBS: dict[str, JobSpec]`.
- `load_all_jobs() -> dict[str, JobSpec]` imports the five stub modules above.
- `request_job(session, kind: str, params: dict | None = None, *, coalesce: bool = True) -> int`: when a `requested` job of the same kind exists and `coalesce` is on, it unions any list-valued params into that job and returns its id.
- `claim_next_request(session) -> JobRequest | None`: `SELECT … FOR UPDATE SKIP LOCKED`, oldest first, then sets `running` and `started_at`.
- `run_request(ctx_builder: Callable[[JobRequest], JobContext], session_factory, request_id: int) -> None`: runs the job. Its return dict goes into `progress["result"]`. The final status is `done`, or `failed` with the error text.
- `track_run(session_factory, job: str) -> ContextManager[RunTracker]`, where `RunTracker` has mutable ints `fetched`, `new_rows`, `missed`, `errors` and a dict `notes`. It writes `ingest_runs` on exit, even on an exception (which it re-raises).
- `BACKFILL_STEPS = ("backfill_reference", "backfill_insiders", "backfill_funds", "backfill_prices", "analytics_full")`, and the job `backfill_all` (registered in `jobs.py`), which runs each step's func in order with its own progress sub-dict and stops at the first failure.
- The job `reparse` (registered in `jobs.py`) takes params `{"accessions": [...]}` or `{"status": "error"}`. It calls `reparse_accession` for each matching filing, committing per filing, and returns `{"parsed": n, "error": m}`.
- `worker.build_scheduler(settings, *, specs: dict[str, JobSpec], ctx_factory) -> BlockingScheduler`:
  - Cron jobs use `CronTrigger(**cron, timezone=ET)`, and interval jobs use `IntervalTrigger`. All have `max_instances=1`, `coalesce=True` and `misfire_grace_time=300`.
  - Adds `poll_job_requests` every 5 s.
  - Executor: `ThreadPoolExecutor(4)`.
- `worker.main()`: configures logging, builds a shared `SecClient` whose `on_block` writes `app_state['sec_blocked_until']`, then starts.
- CLI (`signals`):
  - `migrate`
  - `worker`
  - `api [--host 127.0.0.1] [--port 8000]`
  - `jobs request KIND [--params JSON]`
  - `jobs list [--limit 20]`
  - `reparse [--status error] [--accession ACC]`
  - `openapi --out PATH`

- [ ] **Step 1: Write the failing tests:**
  - `test_request_and_run_job`: register a `demo` job returning `{"n": 1}`, call `request_job`, then `claim_next_request` and `run_request`. Status is `done` and `progress["result"] == {"n": 1}`.
  - `test_failed_job_records_error`: the job raises `RuntimeError("x")`. Status is `failed` with error `"RuntimeError: x"`.
  - `test_coalesce_unions_list_params`: `request_job(s, "analytics_incremental", {"issuer_ciks": [1]})` twice, the second with `[2]`. That produces one row with `params["issuer_ciks"] == [1, 2]`.
  - `test_track_run_writes_row_on_error`: `track_run` records `errors == 1` and the note, and the exception propagates.
  - `test_backfill_all_runs_steps_in_order`: register fake steps that append to a list. The order equals `BACKFILL_STEPS`, and a failing step stops the rest.
  - `test_reparse_job_by_status`: an errored filing whose raw bytes are archived, with a now-working handler registered, gives the result `{"parsed": 1, "error": 0}`.
  - `test_scheduler_uses_et_timezone`: with a spec `cron={"hour": 2, "minute": 0}`, the scheduler job's `trigger.timezone` is ET.
  - `test_cli_jobs_request_and_list` (Typer `CliRunner` with an env pointing at the test database): the output contains the kind and `requested`.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_jobs.py tests/unit/test_cli.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest tests/integration/test_jobs.py tests/unit/test_cli.py`. Expected: all pass.

- [ ] **Step 5: Commit** with message `feat: job registry, worker scheduler, CLI and backfill orchestrator`.

---

### Task 11: API contract, analytics result types, price access

**Files:**
- Create:
  - `backend/src/signals/api/{__init__,main,deps,schemas}.py`
  - `backend/src/signals/api/routers/{__init__,feed,insiders,companies,funds,screener,compare,search,watchlists,health,jobs}.py` (stubs owned by E)
  - `backend/src/signals/analytics/types.py`, `analytics/curves.py` (stub owned by D)
  - `backend/src/signals/prices/base.py`
- Test: `backend/tests/integration/test_api_contract.py`

**Interfaces (produces):**
- `api.main.create_app() -> FastAPI`, with every router under `/api`. An exception handler maps `NotImplementedError` to 501 `{"detail": "not implemented"}`. The module-level `app = create_app()`.
- `api.deps`:
  - `get_db() -> Iterator[Session]`, using `get_settings().database_url` with a module-level engine
  - `CurveService` Protocol, with `insider_curve(session, cik, *, basis, include_10b5_1, as_of) -> Curve` and `fund_curve(session, cik, *, basis, as_of) -> Curve`
  - `get_curve_service() -> CurveService`, which returns the `signals.analytics.curves` module
- `analytics.types`:
  - `WindowResult(window: Window, start: date | None, end: date | None, ret, ret_spy, ret_qqq, ret_sector, annualized, vol, max_drawdown, beta, time_invested_pct)`: all `float | None`, frozen dataclass
  - `Curve(basis: Basis, points: pandas.DataFrame, windows: list[WindowResult], coverage_pct: float | None, as_of: date)`: `points` is indexed by date, with columns `nav`, `spy`, `qqq`, `sector`, each normalized to 1.0 at the first row
- `analytics.curves`: `insider_curve(...)` and `fund_curve(...)` with the signatures above. Both raise `NotImplementedError`.
- `prices.base`:
  - `BAR_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "adj_close", "source")`
  - `PriceProvider` Protocol, with `name: str` and `daily_bars(symbols: Sequence[str], start: date, end: date) -> pd.DataFrame` (the columns above minus `source`)
  - `get_bars(session, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame` (BAR_COLUMNS, sorted by symbol and date)

**`api/schemas.py`.** This is the contract. Write it exactly. All are Pydantic v2 `BaseModel`s. Percentages are fractions.

```python
Basis = Literal["filed", "executed"]; WindowName = Literal["ytd", "1y", "3y", "5y"]
Change = Literal["NEW", "ADD", "TRIM", "EXIT", "SAME"]; ConfidenceName = Literal["low", "medium", "high"]

class OwnerRef(BaseModel): cik: int; name: str
class IssuerRef(BaseModel): cik: int; name: str; ticker: str | None = None
class Rating(BaseModel): score: int | None; confidence: ConfidenceName | None; n: int
class WindowStat(BaseModel):
    window: WindowName; ret: float | None; ret_spy: float | None; ret_qqq: float | None
    ret_sector: float | None; annualized: float | None; vol: float | None
    max_drawdown: float | None; beta: float | None; time_invested_pct: float | None
class AllocationSlice(BaseModel): key: str; label: str; value_usd: float; weight: float
class CurvePoint(BaseModel): date: date; nav: float; spy: float; qqq: float; sector: float
class PerformanceOut(BaseModel):
    basis: Basis; points: list[CurvePoint]; windows: list[WindowStat]; coverage_pct: float | None; as_of: date

class FeedItemOut(BaseModel):
    accession_no: str; sec_url: str; form_type: str; accepted_at: datetime | None; filed_date: date
    issuer: IssuerRef | None; owners: list[OwnerRef]; top_role: str | None
    direction: Literal["buy", "sell", "other"] | None; codes: list[str]
    value_usd: float | None; shares: float | None; price: float | None
    plan_10b5_1: Literal["flag", "footnote", "none"] | None; badges: list[str]
    market_cap_usd: float | None; sector: str | None; summary: str; lag_days: int | None
class FeedPage(BaseModel): items: list[FeedItemOut]; next_cursor: str | None
class ClusterEvent(BaseModel):
    issuer: IssuerRef; start_date: date; end_date: date; owner_count: int; total_value_usd: float
class FeedSummary(BaseModel):
    date: date; counts_by_form: dict[str, int]; top_buys: list[FeedItemOut]; top_sells: list[FeedItemOut]
    clusters: list[ClusterEvent]; late_filings: list[FeedItemOut]

class RoleAtIssuer(BaseModel):
    issuer: IssuerRef; roles: list[str]; officer_title: str | None; first_filed: date | None; last_filed: date | None
class HorizonReturn(BaseModel):
    horizon: Literal["1m", "3m", "6m", "12m"]; raw: float | None; excess_spy: float | None
    excess_qqq: float | None; excess_sector: float | None; complete: bool
class DecisionOut(BaseModel):
    id: int; issuer: IssuerRef; owners: list[OwnerRef]; direction: Literal["buy", "sell"]
    first_trade_date: date; last_trade_date: date; shares: float | None; value_usd: float | None
    vwap: float | None; stake_change_pct: float | None; accepted_at: datetime | None
    plan_10b5_1: Literal["flag", "footnote", "none"]; badges: list[str]; lag_days: int | None
    lag_cost: float | None; returns: list[HorizonReturn]; first_accession: str; sec_url: str
class DecisionPage(BaseModel): items: list[DecisionOut]; next_cursor: str | None
class InsiderHeader(BaseModel):
    cik: int; name: str; owner_type: Literal["person", "entity"]; roles: list[RoleAtIssuer]
    basis: Basis; include_10b5_1: bool; rating: Rating; avg_roi_6m: float | None
    avg_roi_6m_raw: float | None; median_6m: float | None; hit_rate: float | None
    n_decisions: int; n_buys: int; n_sells: int; avg_lag_days: float | None; avg_lag_cost: float | None
    best: DecisionOut | None; worst: DecisionOut | None; risk_label: Literal["low", "medium", "high"] | None
    fund_cik: int | None; updated_at: datetime | None
class TransactionOut(BaseModel):
    accession_no: str; sec_url: str; form_type: str; accepted_at: datetime | None; issuer: IssuerRef
    transaction_date: date | None; code: str | None; code_label: str | None; acquired_disposed: str | None
    shares: float | None; price: float | None; value_usd: float | None; shares_owned_after: float | None
    direct_indirect: str | None; security_title: str | None; table_kind: Literal["nonderiv", "deriv"]
    plan_10b5_1: Literal["flag", "footnote", "none"]; superseded: bool; footnotes: list[str]
class TransactionPage(BaseModel): items: list[TransactionOut]; next_cursor: str | None
class HoldingOut(BaseModel):
    issuer: IssuerRef; security_title: str | None; shares: float | None; value_usd: float | None
    weight: float | None; sector: str | None; direct_indirect: str | None; as_of_date: date | None
class HoldingsOut(BaseModel):
    positions: list[HoldingOut]; derivatives: list[HoldingOut]; by_sector: list[AllocationSlice]
    by_issuer: list[AllocationSlice]; effective_n: float | None; top5_weight: float | None
    total_value_usd: float | None
class Form144Out(BaseModel):
    accession_no: str; sec_url: str; filed_date: date; issuer: IssuerRef; seller_name: str | None
    relationship: str | None; shares_to_sell: float | None; market_value_usd: float | None
    approx_sale_date: date | None; broker: str | None; plan_10b5_1_adopted: date | None
    matched_sale_accession: str | None; status: Literal["pending", "matched", "expired"]

class NetBuying(BaseModel):
    window: Literal["3m", "6m", "12m"]; buys_usd: float; sells_usd: float; net_usd: float
    n_buyers: int; n_sellers: int
class CompanyHeader(BaseModel):
    cik: int; name: str; ticker: str | None; former_tickers: list[str]; exchange: str | None
    sector: str | None; sic: int | None; sic_description: str | None; market_cap_usd: float | None
    latest_close: float | None; latest_close_date: date | None; net_buying: list[NetBuying]
class Bar(BaseModel):
    date: date; open: float; high: float; low: float; close: float; volume: float | None; adj_close: float
class Marker(BaseModel):
    date: date; kind: Literal["buy", "sell", "form144", "stake", "cluster"]; label: str
    value_usd: float | None; ref: str
class PriceSeriesOut(BaseModel): symbol: str | None; bars: list[Bar]; markers: list[Marker]
class InsiderRosterRow(BaseModel):
    owner: OwnerRef; roles: list[str]; last_trade_date: date | None; net_12m_usd: float
    n_decisions: int; rating: Rating
class InstitutionRow(BaseModel):
    fund: OwnerRef; shares: float; value_usd: float; weight_in_fund: float | None; change: Change
    shares_change_pct: float | None; is_tracked: bool
class InstitutionsOut(BaseModel):
    period: date | None; periods_available: list[date]; rows: list[InstitutionRow]
    total_value_usd: float; holders_count: int; new_count: int; exit_count: int; next_cursor: str | None
class StakePerson(BaseModel):
    name: str; cik: int | None; percent_of_class: float | None; shares: float | None
class StakeOut(BaseModel):
    accession_no: str; sec_url: str; form_type: str; filed_date: date; event_date: date | None
    reporting_persons: list[StakePerson]; percent_of_class: float | None; is_activist: bool
    is_current: bool; purpose_excerpt: str | None

class FundValuePoint(BaseModel): period: date; value_usd: float; positions: int
class FundHeader(BaseModel):
    cik: int; name: str; is_tracked: bool; latest_period: date | None; latest_value_usd: float | None
    latest_positions: int | None; value_history: list[FundValuePoint]; rating: Rating
    windows: list[WindowStat]; coverage_pct: float | None; insider_cik: int | None
class SecurityRef(BaseModel): cusip: str; name: str | None; ticker: str | None; issuer_cik: int | None
class FundHoldingRow(BaseModel):
    security: SecurityRef; put_call: str | None; shares: float; value_usd: float; weight: float | None
    prev_weight: float | None; change: Change; shares_change_pct: float | None; sector: str | None
    high_conviction: bool
class FundHoldingsOut(BaseModel):
    period: date | None; periods_available: list[date]; rows: list[FundHoldingRow]
    exits: list[FundHoldingRow]; by_sector: list[AllocationSlice]; effective_n: float | None
    top5_weight: float | None; next_cursor: str | None

class InsiderScreenRow(BaseModel):
    owner: OwnerRef; primary_issuer: IssuerRef | None; roles: list[str]; sector: str | None
    rating: Rating; avg_roi_6m: float | None; hit_rate: float | None; n_decisions: int
    last_trade_date: date | None; windows: dict[str, float | None]; risk_label: str | None
class InsiderScreenPage(BaseModel): items: list[InsiderScreenRow]; next_cursor: str | None
class FundScreenRow(BaseModel):
    fund: OwnerRef; latest_value_usd: float | None; positions: int | None; top_sector: str | None
    rating: Rating; windows: dict[str, float | None]; risk_label: str | None; coverage_pct: float | None
class FundScreenPage(BaseModel): items: list[FundScreenRow]; next_cursor: str | None
class CompareProfile(BaseModel):
    id: str; kind: Literal["insider", "fund"]; name: str; rating: Rating; avg_roi_6m: float | None
    hit_rate: float | None; windows: list[WindowStat]; curve: list[CurvePoint]; by_sector: list[AllocationSlice]
class CompareOut(BaseModel): basis: Basis; profiles: list[CompareProfile]
class SearchHit(BaseModel):
    kind: Literal["insider", "company", "fund"]; cik: int; name: str; ticker: str | None
    subtitle: str | None; score: float
class SearchOut(BaseModel): insiders: list[SearchHit]; companies: list[SearchHit]; funds: list[SearchHit]

class WatchlistItemOut(BaseModel):
    kind: Literal["insider", "company", "fund"]; cik: int; name: str; added_at: datetime
class WatchlistOut(BaseModel): id: int; name: str; items: list[WatchlistItemOut]
class WatchlistCreate(BaseModel): name: str = Field(min_length=1, max_length=80)
class WatchlistItemCreate(BaseModel): kind: Literal["insider", "company", "fund"]; cik: int

class JobStatusOut(BaseModel):
    kind: str; last_started_at: datetime | None; last_finished_at: datetime | None
    last_status: str | None; last_error: str | None
class ParseErrorOut(BaseModel):
    accession_no: str; form_type: str; filed_date: date; error: str; sec_url: str
class BackfillStep(BaseModel):
    step: str; status: str; done_units: int; total_units: int | None; updated_at: datetime | None
class Coverage(BaseModel):
    issuers_with_sector_pct: float | None; cusip_value_mapped_pct: float | None
    decisions_with_prices_pct: float | None; decisions_last_price_exit_pct: float | None
class HealthOut(BaseModel):
    status: Literal["ok", "warn", "error"]; jobs: list[JobStatusOut]; feed_delay_p50_s: float | None
    feed_delay_p95_s: float | None; last_filing_seen_at: datetime | None
    parse_errors: list[ParseErrorOut]; backfill: list[BackfillStep]; coverage: Coverage
    sec_blocked_until: datetime | None
class JobRequestIn(BaseModel): kind: str; params: dict[str, Any] = {}
class JobRequestOut(BaseModel):
    id: int; kind: str; status: str; requested_at: datetime; finished_at: datetime | None; error: str | None
```

**Router stubs.** These are the exact paths, query parameters and response models. Bodies raise `NotImplementedError`, except `GET /api/health`, which returns `HealthOut(status="ok", jobs=[], feed_delay_p50_s=None, feed_delay_p95_s=None, last_filing_seen_at=None, parse_errors=[], backfill=[], coverage=Coverage(…all None), sec_blocked_until=None)`.

- `limit` defaults to 50 (max 500) and `cursor` is `str | None` everywhere.
- Every list endpoint also accepts `format: Literal["json","csv"] = "json"`.

| Method and path | Query parameters | Response |
|---|---|---|
| `GET /api/feed` | `forms: list[str]`, `direction: list[str]`, `codes: list[str]`, `roles: list[str]`, `sectors: list[str]`, `badges: list[str]`, `min_value`, `max_value`, `min_mcap`, `max_mcap` (float), `include_10b5_1: bool = True`, `trade_from`, `trade_to`, `filed_from`, `filed_to` (date), `max_lag_days: int`, `issuer_cik: int`, `owner_cik: int` | `FeedPage` |
| `GET /api/feed/summary` | `date: date \| None` | `FeedSummary` |
| `GET /api/insiders/{cik}` | `basis="filed"`, `include_10b5_1=False` | `InsiderHeader` |
| `GET /api/insiders/{cik}/decisions` | `basis`, `include_10b5_1`, `direction: str \| None` | `DecisionPage` |
| `GET /api/insiders/{cik}/transactions` | `codes: list[str]`, `issuer_cik: int \| None`, `include_superseded=False` | `TransactionPage` |
| `GET /api/insiders/{cik}/performance` | `basis`, `include_10b5_1` | `PerformanceOut` |
| `GET /api/insiders/{cik}/holdings` | none | `HoldingsOut` |
| `GET /api/insiders/{cik}/form144` | none | `list[Form144Out]` |
| `GET /api/companies/{ref}` | none (`ref` is a CIK or a ticker) | `CompanyHeader` |
| `GET /api/companies/{cik}/prices` | `start: date \| None`, `end: date \| None`, `markers=True` | `PriceSeriesOut` |
| `GET /api/companies/{cik}/insiders` | `include_10b5_1=False` | `list[InsiderRosterRow]` |
| `GET /api/companies/{cik}/institutions` | `period: date \| None` | `InstitutionsOut` |
| `GET /api/companies/{cik}/stakes` | `current_only=False` | `list[StakeOut]` |
| `GET /api/companies/{cik}/form144` | `status: str \| None` | `list[Form144Out]` |
| `GET /api/funds/{cik}` | none | `FundHeader` |
| `GET /api/funds/{cik}/holdings` | `period: date \| None` | `FundHoldingsOut` |
| `GET /api/funds/{cik}/performance` | `basis` | `PerformanceOut` |
| `GET /api/screener/insiders` | `roles`, `sectors` (list), `min_decisions: int = 1`, `last_trade_from`, `last_trade_to`, `min_rating: int`, `confidence: list[str]`, `window: WindowName = "1y"`, `min_return`, `max_return`, `risk: list[str]`, `basis`, `include_10b5_1`, `sort="rating"`, `order="desc"` | `InsiderScreenPage` |
| `GET /api/screener/funds` | `sectors`, `min_rating`, `confidence`, `window`, `min_return`, `max_return`, `risk`, `basis`, `tracked_only=True`, `sort="rating"`, `order="desc"` | `FundScreenPage` |
| `GET /api/compare` | `ids: str` (for example `insider:123,fund:456`), `basis`, `include_10b5_1` | `CompareOut` |
| `GET /api/search` | `q: str` (min length 2), `limit: int = 8` | `SearchOut` |
| `GET, POST /api/watchlists` | POST body `WatchlistCreate` | `list[WatchlistOut]` for GET, `WatchlistOut` (201) for POST |
| `GET, DELETE /api/watchlists/{watchlist_id}` | none | `WatchlistOut` for GET, 204 for DELETE |
| `POST /api/watchlists/{watchlist_id}/items` | body `WatchlistItemCreate` | `WatchlistOut` |
| `DELETE /api/watchlists/{watchlist_id}/items/{kind}/{cik}` | none | 204 |
| `GET /api/watchlists/{watchlist_id}/activity` | `cursor`, `limit` | `FeedPage` |
| `GET /api/health` | none | `HealthOut` |
| `GET, POST /api/jobs` | GET `limit=20`; POST body `JobRequestIn` | `list[JobRequestOut]` for GET, `JobRequestOut` (202) for POST |

- [ ] **Step 1: Write the failing tests:**

```python
PATHS = {"/api/feed","/api/feed/summary","/api/insiders/{cik}","/api/insiders/{cik}/decisions",
 "/api/insiders/{cik}/transactions","/api/insiders/{cik}/performance","/api/insiders/{cik}/holdings",
 "/api/insiders/{cik}/form144","/api/companies/{ref}","/api/companies/{cik}/prices",
 "/api/companies/{cik}/insiders","/api/companies/{cik}/institutions","/api/companies/{cik}/stakes",
 "/api/companies/{cik}/form144","/api/funds/{cik}","/api/funds/{cik}/holdings","/api/funds/{cik}/performance",
 "/api/screener/insiders","/api/screener/funds","/api/compare","/api/search","/api/watchlists",
 "/api/watchlists/{watchlist_id}","/api/watchlists/{watchlist_id}/items",
 "/api/watchlists/{watchlist_id}/items/{kind}/{cik}","/api/watchlists/{watchlist_id}/activity",
 "/api/health","/api/jobs"}

def test_openapi_has_every_path(client):
    assert PATHS == set(client.get("/api/openapi.json").json()["paths"])

def test_stub_returns_501(client):
    assert client.get("/api/feed").status_code == 501

def test_health_ok(client):
    r = client.get("/api/health"); assert r.status_code == 200 and r.json()["status"] == "ok"

def test_get_bars_sorted(session):
    make_prices(session, "ACME", date(2024, 1, 2), [10, 11]); make_prices(session, "AAA", date(2024, 1, 2), [5])
    df = get_bars(session, ["ACME", "AAA"], date(2024, 1, 1), date(2024, 1, 31))
    assert list(df.columns) == list(BAR_COLUMNS) and list(df["symbol"]) == ["AAA", "ACME", "ACME"]
```

  `client` is a fixture: `TestClient(create_app())` with `get_db` overridden to yield the test `session`. Set `openapi_url="/api/openapi.json"` in `create_app`.

- [ ] **Step 2:** Run `uv run pytest tests/integration/test_api_contract.py`. Expected: FAIL.

- [ ] **Step 3:** Implement.

- [ ] **Step 4:** Run `uv run pytest -q`. Expected: all pass. Then run `uv run signals openapi --out ../frontend/src/api/openapi.json`, which writes the file used in Task 12.

- [ ] **Step 5: Commit** with message `feat: API contract (schemas and route stubs), analytics result types, price access`.

---

### Task 12: Frontend skeleton

**Files:**
- Create in `frontend/`:
  - `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json`, `eslint.config.js`, `index.html`, `components.json`
  - `src/main.tsx`, `src/App.tsx`, `src/index.css`, `src/lib/utils.ts`, `src/lib/env.ts`
  - `src/api/openapi.json` (from Task 11), `src/api/schema.d.ts` (generated), `src/api/client.ts`
  - `src/components/layout/AppShell.tsx`
  - Page stubs (F): `src/pages/{Feed,Insider,Company,Fund,Screener,Compare,Watchlists,Health,NotFound}Page.tsx`
  - `src/mocks/{handlers.ts,browser.ts,node.ts}`, `src/test/setup.ts`
  - `vitest.config.ts`, `playwright.config.ts`
- Test: `frontend/src/App.test.tsx`

**Pinned versions** (exact):
- dependencies: `react@19.3.0`, `react-dom@19.3.0`, `react-router@7.18.4`, `@tanstack/react-query@5.104.0`, `@tanstack/react-table@8.21.3`, `@tanstack/react-virtual@3.14.13`, `lightweight-charts@5.2.1`, `recharts@3.10.1`, `openapi-fetch@0.17.0`, `cmdk@1.1.1`, `lucide-react@1.48.0`
- devDependencies: `vite@8.3.1`, `@vitejs/plugin-react@6.1.1`, `typescript@5.9.3` (changed from 6.0.3 during execution: openapi-typescript peer), `tailwindcss@4.3.3`, `@tailwindcss/vite@4.3.3`, `openapi-typescript@7.13.0`, `msw@2.15.0`, `vitest@4.1.11`, `jsdom@30.1.1`, `@testing-library/react@16.3.3`, `@testing-library/jest-dom@7.0.1`, `@testing-library/user-event`, `@playwright/test@1.63.0`, `eslint@9.39.5`, `typescript-eslint@8.70.1`, `eslint-plugin-react-hooks@7.1.1`, `@types/react@19.3.0`, `@types/react-dom@19.3.0`, `@types/node`

**Scripts:** `dev` (vite), `build` (`tsc -b && vite build`), `test` (`vitest run`), `lint`, `gen:api` (`openapi-typescript src/api/openapi.json -o src/api/schema.d.ts`), `e2e` (`playwright test`).

**Interfaces (produces):**
- `src/api/client.ts` exports `api = createClient<paths>({ baseUrl: "/" })` and the type helper `type Schema<K extends keyof components["schemas"]> = components["schemas"][K]`.
- **Routes:** `/` → FeedPage, `/insider/:cik`, `/company/:ref`, `/fund/:cik`, `/screener`, `/compare`, `/watchlists`, `/health`, `*` → NotFound. Use `createBrowserRouter` and `RouterProvider` from `react-router`, wrapped in `QueryClientProvider` (`staleTime` 30 s).
- **AppShell:**
  - Top nav links: Feed, Screener, Compare, Watchlists, Health.
  - A search trigger button labelled `Search (⌘K)`, filled in by F.
  - A theme toggle that sets `class="dark"` on `<html>` and stores the choice in `localStorage['theme']`, wrapped in try/catch.
  - A `<footer>` with exactly `Data from SEC EDGAR. Not investment advice.`
- **Vite:** `server.proxy['/api'] = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'`, and `server.host = '127.0.0.1'` unless `VITE_HOST` is set. MSW starts in the browser only when `import.meta.env.VITE_MOCK === '1'`.
- **Tailwind:** v4 via `@tailwindcss/vite`. `index.css` holds `@import "tailwindcss";` plus CSS-variable theme tokens for light and `.dark`. The shadcn/ui config (`components.json`) aliases `@/components`, `@/lib`, `@/components/ui`. Install these components with `npx shadcn@latest add`: `button input badge card tabs table dialog command dropdown-menu select tooltip skeleton toggle-group separator scroll-area sheet popover switch`.

- [ ] **Step 1: Scaffold.** Write the files, then run `npm install`.

- [ ] **Step 2: Write the failing test** `src/App.test.tsx`:

```tsx
it("renders navigation and footer", async () => {
  render(<AppWithRouter initialPath="/" />);
  for (const name of ["Feed", "Screener", "Compare", "Watchlists", "Health"])
    expect(screen.getByRole("link", { name })).toBeInTheDocument();
  expect(screen.getByText("Data from SEC EDGAR. Not investment advice.")).toBeInTheDocument();
});
```

  `AppWithRouter` is exported from `App.tsx` and uses `createMemoryRouter`.

- [ ] **Step 3:** Run `npm test`. Expected: FAIL (the component isn't implemented yet).

- [ ] **Step 4:** Implement AppShell and the routes. Then run `npm run gen:api`, `npm test`, `npm run build` and `npm run lint`. Expected: all succeed.

- [ ] **Step 5: Commit** with message `feat: frontend skeleton (router, query client, theme, API types, mocks)`.

---

### Task 13: Full Compose stack

**Files:**
- Create: `backend/Dockerfile`, `frontend/Dockerfile.dev`
- Modify: `docker-compose.yml`

**Services:**
- `db`: unchanged.
- `migrate`:
  - Built from `backend`. Command `signals migrate`.
  - `env_file: .env`, with `DATABASE_URL=postgresql+psycopg://signals:${POSTGRES_PASSWORD}@db:5432/signals`.
  - `depends_on: db (service_healthy)`.
- `api`:
  - Same image. Command `signals api --host 0.0.0.0 --port 8000`.
  - Ports `127.0.0.1:8000:8000`.
  - `depends_on: migrate (service_completed_successfully)`.
- `worker`:
  - Same image. Command `signals worker`.
  - Volume `./data:/app/data`, and `RAW_ARCHIVE_DIR=/app/data/raw`.
  - Depends on `migrate`.
- `web`:
  - Built from `frontend/Dockerfile.dev` (node:26, `npm ci`, `npm run dev -- --host 0.0.0.0`).
  - Ports `127.0.0.1:5173:5173`.
  - `VITE_API_PROXY=http://api:8000`, `VITE_HOST=0.0.0.0`.

`backend/Dockerfile`: `python:3.13-slim`, then `COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv`, then `uv sync --frozen --no-dev`, with `ENTRYPOINT ["uv","run","--no-sync"]`.

- [ ] **Step 1:** Run `docker compose up -d --build`.

- [ ] **Step 2:** Run `curl -s 127.0.0.1:8000/api/health`. Expected: JSON with `"status":"ok"`.

- [ ] **Step 3:** Run `curl -s 127.0.0.1:5173 | grep -c '<div id="root">'`. Expected: `1`.

- [ ] **Step 4:** Run `docker compose logs worker | tail -5`. Expected: a scheduler-started log line and no traceback.

- [ ] **Step 5: Commit** with message `chore: full Docker Compose stack (db, migrate, api, worker, web)`.

---

### Task 14: CLAUDE.md, README, foundation tag

**Files:**
- Create: `CLAUDE.md`, `README.md`

**CLAUDE.md contents:**
- The architecture, in one paragraph.
- The ground rules from spec §5.4.
- **Hard rules:**
  - Never measure follower returns from the trade date alone.
  - Never key anything by ticker.
  - Never delete raw data.
  - Every SEC request goes through `SecClient`.
- The ownership table from `00-overview.md`.
- **Commands:** `docker compose up -d db`, `uv run pytest -q`, `uv run ruff check`, `uv run pyright`, `npm test`, `npm run build`, `npx playwright test`, `uv run signals jobs request backfill_all`.

**README contents:** setup (Docker Desktop, `.env` from `.env.example`, `docker compose up`), where to open it (`http://localhost:5173`), and how to start the backfill.

- [ ] **Step 1:** Write both files. Run `uv run pytest -q && (cd ../frontend && npm test && npm run build)`. Expected: all green.

- [ ] **Step 2:** Commit with message `docs: CLAUDE.md and README`. Then run `git tag foundation`.
