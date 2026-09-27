# SEC Insider Dashboard: Design Spec (Sub-project 1: SEC core + dashboard)

- **Date:** 2026-09-27
- **Status:** Draft for review
- **Requirements source:** the feature list pasted in the 2026-09-26 session (sections A–D, market data, profile analytics, signals and alerts, UX, data science). The earlier "Insider Signal App" blueprint PDF is background only.

## 1. Context

The full product tracks four groups (company insiders, 13F funds, members of Congress, senior officials), measures each person's track record, and alerts on new trades. That is five sub-projects that share one core. Each gets its own spec, plan and build.

| # | Sub-project | Status |
|---|---|---|
| 1 | **SEC core + dashboard** | **This spec** |
| 2 | Signals & alerts | Later |
| 3 | Congress | Later |
| 4 | Senior officials | Later |
| 5 | Research lab | Later |

Section 15 lists what each later sub-project covers, so nothing from the requirements is lost.

## 2. Goal and success criteria

**Goal:** a local web dashboard that shows every SEC insider trade (Forms 3/4/5), planned insider sale (Form 144), 5%+ stake (Schedules 13D/13G) and fund holding (Form 13F) since 2016, updated within minutes of filing, with every insider's and fund's track record measured from both the trade date and the filing date.

**Done when:**

1. `docker compose up` starts the database, API, worker and web app, and the dashboard opens at `http://localhost:5173`.
2. Backfill is complete: Forms 3/4/5 and 13F from 2016-01-01, Form 144 from 2023-04-13, Schedules 13D/13G from 2024-12-18, and daily prices from 2016-01-01 for every traded ticker and benchmark.
3. While the worker runs, the p95 delay from SEC acceptance to the filing appearing in the feed is 2 minutes or less, as reported on the Data health page.
4. A spot-check script compares 20 random filings field by field against a fresh parse of the SEC original, all 20 match, and the user checks 5 of them by eye on sec.gov.
5. Every insider with at least one discretionary trade has a profile with trades, holdings, returns on both bases, and a reliability rating with a confidence label. Every 13F filer has holdings by quarter with changes. Every tracked fund has copycat performance.
6. All backend and frontend tests pass, type checks are clean, and a browser smoke test loads every page.

## 3. Decisions

| Decision | Choice | Reason |
|---|---|---|
| Audience | The user now, public later | No login in v1. A `users` table with one default user keeps watchlists ready for accounts. |
| History depth | From 2016-01-01 (configurable) | Real 5-year windows with depth behind each rating. Matches Alpaca's free price history. |
| Stack | Python API + React app | Python has the SEC and data tooling. React handles screeners, comparisons and linked charts. The same API can later serve a public app. |
| SEC data | EDGAR directly (feed, indexes, bulk data sets) | Free, authoritative, and carries CIKs, accession numbers and the 10b5-1 flag. |
| Prices | Alpaca Market Data (free Basic plan), yfinance fallback | Alpaca is keyed, reliable and covers 2016 onward. yfinance works with no key. |
| Database | PostgreSQL 17 in Docker | Relational data, concurrent writers, partitioning for 13F. |
| Build | Foundation first, then 6 parallel subagents | The user set a limit of 6 subagents. |

## 4. Scope

**In scope**

- Forms 3, 4, 5 and amendments: every transaction and holding row, for officers, directors, 10% owners and others.
- Form 144 notices of proposed sales (electronic since 2023-04-13).
- Schedules 13D and 13G in XML (required since 2024-12-18), with percent of class and activist (13D) versus passive (13G).
- Form 13F-HR holdings with quarter-over-quarter changes (new, add, trim, exit), market value, and open or closed positions.
- Daily prices for every traded ticker, plus SPY, QQQ and the 11 SPDR sector ETFs.
- Per-person and per-fund analytics: positions, per-trade returns on both bases, YTD/1/3/5-year copycat performance against SPY, QQQ and a sector-matched benchmark, reliability rating, allocation, concentration, risk, and badges.
- Dashboard: live feed, insider profile, company page, fund page, screener and leaderboard, compare, search, watchlists, data health, CSV export.

**Out of scope for this sub-project** (covered later, see section 15)

- Alerts and bots, scoring rules, outperformer flags.
- Congress, senior officials.
- Edge score, signal simulation, event correlation, options chains and options ideas.

**Not planned for v1 at all**

- Logins, and deployment to a server.
- Form 144 before 2023-04-13 (paper filings).
- 13D/13G before 2024-12-18 (HTML only, no structured percentages).
- Earnings calendar.

## 5. Architecture

### 5.1 Processes (Docker Compose)

| Service | What it runs | Notes |
|---|---|---|
| `db` | PostgreSQL 17 | Named volume. Port bound to 127.0.0.1 only. |
| `worker` | Python scheduler (APScheduler) running every job in 5.3 | The only process that talks to SEC, Alpaca and OpenFIGI. |
| `api` | FastAPI (uvicorn) on port 8000 | Reads the database. Never calls SEC. Bound to 127.0.0.1. |
| `web` | Vite dev server for the React app on port 5173 | Proxies `/api` to `api`. |

In development the API and web app may also run natively against the Compose database.

### 5.2 Repository layout

```
Signals/
  docker-compose.yml  .env.example  .gitignore  CLAUDE.md  README.md
  docs/superpowers/{specs,plans}/
  backend/
    pyproject.toml  uv.lock  alembic.ini  migrations/
    src/signals/
      config.py                 settings from .env (pydantic-settings)
      db/                       engine, session, SQLAlchemy models
      sec/                      HTTP client, rate limiter, raw archive, SGML .txt reader
      ingest/
        feed.py                 live Atom poller
        daily_index.py          nightly reconcile
        full_index.py           accession lists for gap fills
        bulk_345.py             Insider Transactions Data Sets loader
        bulk_13f.py             Form 13F Data Sets loader
        gap_fill.py             per-filing fetch for anything bulk data lacks
        parsers/                ownership.py (3/4/5), form144.py, form13f.py, schedule13dg.py
        normalize.py            canonical rows, amendments, joint filings, feed_items
      reference/                companies.py (submissions.zip), sectors.py (SIC map + CSV),
                                shares.py (XBRL frames), cusip.py (OpenFIGI + name match)
      prices/                   base.py (provider protocol), alpaca.py, yfinance_provider.py, loader.py
      analytics/                decisions.py, entries.py, returns.py, copycat.py, funds.py,
                                ratings.py, allocation.py, badges.py, roles.py, run.py
      api/                      main.py, schemas.py, routers/*.py
      jobs.py                   job registry and job-request table handling
      worker.py                 scheduler entry point
      cli.py                    `signals …` commands (Typer)
    tests/
      fixtures/sec/…            recorded real filings, feed pages, index files, bulk slices
      unit/  integration/
  frontend/
    package.json  vite.config.ts  src/{api,pages,components,lib}/  tests/
  scripts/
    record_fixture.py           saves a real filing into tests/fixtures
    spot_check.py               success criterion 4
```

### 5.3 Job schedule (all times US Eastern)

| Job | When | What |
|---|---|---|
| `live_poll` | Every 60 s, 06:00–22:00 on business days | Read the Atom feed for each tracked form type and ingest new accessions (7.2). |
| `reconcile_daily` | 06:30 daily | Diff the previous business day's daily index against `filings` and fetch anything missing (7.3). |
| `reference_refresh` | Sundays 04:00; tickers daily 05:00 | `submissions.zip`, `company_tickers_exchange.json`, XBRL shares outstanding (7.7). |
| `prices_daily` | 18:30 on trading days | New bars for every symbol in the price universe (7.8). |
| `analytics_incremental` | After each ingest batch with new decisions | Recompute affected profiles only. |
| `analytics_full` | 02:00 daily | Recompute every derived table (9.10). |
| `backfill` | On request, resumable | The steps in 7.4. |
| `bulk_dataset_check` | Mondays 03:00 | Load newly published Insider or 13F data sets, skipping accessions already parsed. |

Jobs are requested through a `job_requests` table (from the CLI or the Data health page) and run by the worker, so all outside traffic shares one rate limiter.

### 5.4 Ground rules

1. **Raw data is never deleted.** Every fetched filing `.txt`, feed page, index file and bulk ZIP is stored gzip-compressed under `RAW_ARCHIVE_DIR`, so parsers can be fixed and data re-derived (`signals reparse`).
2. **Every job is idempotent.** Writes are upserts keyed by natural keys (accession number, CIK, symbol and date). Re-running is always safe.
3. **Keys:** companies and people are keyed by SEC CIK, filings by accession number, and 13F securities by CUSIP. Tickers are only a dated lookup, because they change and get reused.
4. **Measure from publication.** Every filing stores its SEC acceptance timestamp. Follower returns are measured from the first tradable price after acceptance, never from the trade date alone.
5. **No silent failures.** Every error is recorded where the Data health page can show it.

## 6. Data sources

| Source | Used for | Format and coverage | Limits |
|---|---|---|---|
| EDGAR latest-filings Atom feed: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=<form>&owner=include&count=100&start=<n>&output=atom` | Live poll | Newest 100 entries per page. `type` prefix-matches (for example `4` also matches `424B2`), so filter entries by exact category term. | SEC fair access: at most 10 requests/s in total, and a User-Agent with a contact email. We cap at 8/s. |
| Daily index: `https://www.sec.gov/Archives/edgar/daily-index/<YYYY>/QTR<n>/form.<YYYYMMDD>.idx` | Nightly reconcile | Every filing of a business day | same |
| Full index: `https://www.sec.gov/Archives/edgar/full-index/<YYYY>/QTR<n>/form.idx` | Accession lists for gap fills | Every filing of a quarter | same |
| Filing text: `https://www.sec.gov/Archives/edgar/data/<cik>/<accession>.txt` | Each individual filing | SGML wrapper with `<ACCEPTANCE-DATETIME>` plus every embedded document, including the XML | same |
| Insider Transactions Data Sets: `https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets` | Forms 3/4/5 backfill | Quarterly ZIP of TSVs (`YYYYqN_form345.zip`, 8–13 MB each), 2006Q1 to 2026Q2 as of 2026-09-27. Filings after 17:30 on a quarter's last business day land in the next set. | same |
| Form 13F Data Sets: `https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets` | 13F backfill | ZIP of TSVs (80–95 MB each). Quarterly names through Feb 2024, then 3-month filing-date ranges such as `01jun2026-31aug2026_form13f.zip`. Download paths differ by year, so links are scraped from the listing page, never built by hand. | same |
| `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` | Company names, SIC codes, tickers, exchanges, and `acceptanceDateTime` for every bulk-loaded filing | Nightly ZIP of per-CIK JSON (1–2 GB). Overflow files (`CIK…-submissions-001.json`) hold older filings. | Refreshed weekly |
| XBRL frames: `https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY<YYYY>Q<n>I.json` | Shares outstanding, used for market cap | One JSON per quarter for all companies | same |
| `https://www.sec.gov/files/company_tickers_exchange.json` | Current ticker, CIK and exchange | JSON | same |
| OpenFIGI: `https://api.openfigi.com/v3/mapping` | CUSIP to ticker for 13F holdings | JSON POST batches | Free. An optional key raises the limits. Check the current limits when implementing. |
| Alpaca Market Data: `https://data.alpaca.markets/v2/stocks/bars` | Daily bars, raw and adjusted (`adjustment=raw` and `adjustment=all`), from 2016 | JSON, many symbols per request | Free Basic plan, 200 requests/min, needs an Alpaca account |
| yfinance | Fallback daily prices when there's no Alpaca key or Alpaca lacks a symbol | Python library over unofficial Yahoo endpoints | Rate-limited and fragile, so fallback only |

## 7. Ingestion

### 7.1 SEC client

- There is a single `SecClient` built on `httpx`, with a token-bucket limiter. The budget comes from `SEC_RATE_LIMIT` (default 8/s), and live-poll requests are served before backfill requests.
- Every request sends `User-Agent: <SEC_USER_AGENT>` from `.env`, which must be a name plus an email. The worker refuses to start without it.
- Timeouts are 5 s to connect and 30 s to read. Timeouts, 429 and 5xx responses are retried up to 5 times with exponential backoff and jitter.
- A 403 response is treated as an SEC block. All SEC traffic pauses for 10 minutes, an error is logged, and Data health turns red.
- Every response body is written to the raw archive before parsing.
- `SgmlFiling.from_txt(bytes)` reads a filing `.txt` and returns the header fields (accession, form type, filed date, acceptance datetime, filer and subject CIKs) plus a list of its documents.

### 7.2 Live poll

1. For each form type (`3`, `4`, `5`, `144`, `13F-HR`, `SCHEDULE 13D`, `SCHEDULE 13G`), plus `/A` variants matched through the category term, fetch feed page `start=0`.
2. Keep fetching the next page (`start=100`, `start=200`, …) until a page contains an accession already stored, or 5 pages have been read.
3. For each new accession, fetch the filing `.txt`, archive it, parse it, normalize it and commit, all in one database transaction per filing.
4. Record `first_seen_at` for each filing so the feed delay (`first_seen_at − accepted_at`) can be measured.

Filings accepted after 17:30 may not show in the feed until the next morning. The nightly reconcile and the entry-price rule (9.2) both handle this.

### 7.3 Nightly reconcile

Read the previous business day's `form.<date>.idx`. Take every accession of a tracked form type that isn't already in `filings`, fetch it through the same path as the live poll, and log how many the live feed missed in `ingest_runs`.

### 7.4 Backfill (resumable)

Each step records completion per unit (per ZIP, per quarter index, per accession), so a restart continues where it stopped.

1. **Reference:** load `submissions.zip` and `company_tickers_exchange.json`, and build `issuers`, `tickers` and a `filing_acceptance` map from accession to `acceptanceDateTime`.
2. **Insider data sets, 2016Q1 through the latest published quarter:** download each ZIP (kept as raw), load its TSVs into staging tables, and normalize them into the canonical tables with acceptance times from step 1. Filings without an acceptance time fall back to the rule in 9.2.
3. **13F data sets from 2016Q1:** same approach. Scrape the listing page for every ZIP that covers filings from 2016 onward and dedupe by accession, because the date-range sets overlap the old quarterly ones.
4. **Gap fill, per filing, using accession lists from the full and daily indexes:**
   - Forms 3/4/5 filed after the last insider data set.
   - 13F filed after the last 13F data set.
   - Every Form 144 since 2023-04-13.
   - Every `SCHEDULE 13D` and `SCHEDULE 13G` (and `/A`) since 2024-12-18.
   - That's roughly 250k requests, about 9 hours at 8/s.
5. **CUSIP mapping** for every CUSIP seen in 13F holdings (7.7).
6. **Prices** from 2016-01-01 for the whole price universe (7.8).
7. **Full analytics recompute.**

Progress for each step shows on the Data health page.

### 7.5 Parsers

Parsers are pure functions: bytes in, typed dataclasses out. They never touch the database. Element names are confirmed against the SEC XML technical specification for each form and against recorded fixtures.

**Forms 3/4/5 (+/A), `ownershipDocument`**
- **Issuer:** CIK, name and `issuerTradingSymbol`. The symbol is stored as dated ticker evidence.
- **Reporting owners (one or more):** CIK, name, director, officer, officer title, 10% owner, other, and other text.
- **Filing level:** `aff10b5One` (the 10b5-1 checkbox, 2023 onward), `dateOfOriginalSubmission` (amendments only), and remarks.
- **Non-derivative transactions:** security title, transaction date, deemed execution date, transaction code, equity swap, shares, price per share, acquired or disposed, shares (or value) owned afterwards, direct or indirect, and nature of ownership.
- **Non-derivative holdings:** the same ownership fields.
- **Derivative transactions and holdings:** additionally conversion or exercise price, exercise date, expiration date, and underlying title and shares.
- **Footnotes:** id to text. A field can carry a footnote reference instead of a value. We store the value as null and keep the reference.
- **Gotchas to handle:**
  - Values are wrapped in `<value>` elements.
  - Booleans appear as `1`, `0`, `true` or `false`.
  - Dates can carry a timezone suffix (`2024-01-15-05:00`).
  - Prices can be missing or given only as a footnote range.
  - The shares owned afterwards can be missing.
  - A transaction can be reported as a value instead of a share count.

**Form 144.** Issuer CIK and name, the seller's name and relationship to the issuer, security class, broker, shares to be sold, aggregate market value, shares outstanding, approximate sale date, exchange, how and when the shares were acquired, securities sold in the past 3 months, and the 10b5-1 plan adoption date if one is given.

**Form 13F-HR (+/A)**
- **Cover and summary:** period of report, amendment flag and type (`RESTATEMENT` or `NEW HOLDINGS`), other included managers, table entry total and table value total.
- **Information table rows:** issuer name, title of class, CUSIP, FIGI (optional), value, shares or principal amount and its type (`SH`/`PRN`), put or call, investment discretion, other manager, and voting authority (sole, shared, none).
- **Unit change:** `value` is in thousands of dollars for filings made before 2023-01-03 and in whole dollars from then on. It's normalized to dollars by filing date. A sanity check flags any row whose implied price per share is more than 100 times off the market close.

**Schedules 13D/13G (XML)**
- Issuer CIK, CUSIP and name, the event date, and amendment number.
- **Per reporting person:** name, CIK if any, sole and shared voting and dispositive power, aggregate amount owned, percent of class, and type of reporting person.
- **13D only:** the Item 4 (purpose) text, truncated to 4,000 characters.

### 7.6 Amendments, joint filings, dedupe

- **Form 3/4/5 amendments.** An amendment restates the original form, so it's matched to its original: same form type without `/A`, same issuer, at least one reporting owner in common, and filed on `dateOfOriginalSubmission`.
  - The original's rows are marked `superseded_by = <amendment accession>`.
  - Several candidates: pick the one whose transaction dates overlap most. No candidate: keep the amendment's rows and flag them `orphan_amendment`.
  - Bulk data sets provide `DATE_OF_ORIG_SUB` and are matched the same way.
- **13F amendments.** A `RESTATEMENT` replaces that filer's holdings for the period. `NEW HOLDINGS` adds rows. A `13F-NT` has no holdings.
- **13D/13G.** The newest filing per filer group and issuer is the current stake. History is kept.
- **Joint filings** (one filing listing several reporting owners):
  - Transactions are stored once per filing and linked to every owner through `filing_owners`.
  - Profiles show the trade under each owner.
  - Population statistics, cluster detection and leaderboards count it once. The owner group is the sorted set of owner CIKs on the filing.
- **Across sources,** the accession number is the key. A bulk data set row is skipped when that accession has already been parsed from XML.

### 7.7 Reference data

- **Issuers:** name, SIC code and description, exchange, state of incorporation, fiscal year end, and active flag, all from `submissions.zip`.
- **Sector:** SIC codes map to 11 sectors through the versioned file `reference/sic_sectors.csv` (ranges plus exceptions such as 6798 REITs → Real Estate). Each sector maps to one ETF: XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY. The mapping is approximate, and its coverage shows on Data health.
- **Tickers** are dated, with `valid_from` and `valid_to` built from each filing's `issuerTradingSymbol` plus the current SEC list. The current ticker is the row with an open `valid_to`.
- **Shares outstanding** come from the XBRL frames API once per quarter. Market cap is shares outstanding times the latest close.
- **CUSIP to security:**
  1. OpenFIGI mapping in batches (US equity composite ticker first).
  2. Otherwise, match the issuer name to SEC issuers and use that issuer's current ticker.
  3. Otherwise leave it unresolved, with a flag.
  Coverage (the share of 13F value mapped to a priced ticker) shows on Data health.

### 7.8 Prices

- **Price universe:** every current or historical ticker of an issuer with a Form 4 transaction since 2016, every ticker mapped from 13F holdings of tracked funds, plus SPY, QQQ and the 11 sector ETFs.
- **Provider interface:** `PriceProvider.daily_bars(symbols, start, end) -> DataFrame[symbol, date, open, high, low, close, volume, adj_close]`.
- **Alpaca** fetches the raw and fully adjusted bars in two requests per batch and stores both, so `adj_factor = adj_close / close` for any date.
- **Fallback:** yfinance (`auto_adjust=False`, which returns both raw and adjusted) fills symbols Alpaca lacks. Each row records its source.
- **Missing data:** no price is ever made up. A missing bar leaves any return that depends on it empty, with a stated reason.
- **Calendars:** an exchange-calendar library (NYSE) supplies trading days, early closes and holidays for everything price-related. Filing-lateness checks (9.8) use SEC business days instead, which follow the US federal holiday calendar. The two differ: NYSE closes on Good Friday but SEC doesn't, and SEC closes on Columbus Day and Veterans Day but NYSE doesn't.

## 8. Data model

All timestamps are `timestamptz`, and business-day logic uses US Eastern. Every table has `created_at`, and mutable tables have `updated_at`.

**Reference**
- `issuers(cik PK, name, sic, sic_description, sector, exchange, state_of_inc, fiscal_year_end, shares_outstanding, shares_outstanding_as_of, is_active)`
- `tickers(id PK, issuer_cik FK, symbol, valid_from, valid_to, source)`, unique on `(symbol, valid_from)`
- `securities(cusip PK, issuer_cik FK NULL, ticker NULL, name, title_of_class, figi, security_type, map_source, map_status)`

**People and filings**
- `owners(cik PK, name, owner_type ('person'|'entity'))`
- `owner_roles(owner_cik, issuer_cik, is_director, is_officer, officer_title, roles text[], is_ten_pct_owner, is_other, other_text, first_filed, last_filed)`, with PK `(owner_cik, issuer_cik)`. `roles` holds the normalized roles from 9.9.
- `filings(accession_no PK, form_type, issuer_cik NULL, primary_cik, filed_date, accepted_at NULL, accepted_at_source, period_of_report, is_amendment, amends_accession NULL, source ('feed'|'daily_index'|'full_index'|'bulk_345'|'bulk_13f'), raw_path, parse_status ('pending'|'parsed'|'error'|'skipped'), parse_error, first_seen_at, parsed_at)`
- `filing_owners(accession_no, owner_cik, is_director, is_officer, officer_title, is_ten_pct_owner, is_other)`, with PK `(accession_no, owner_cik)`

**Insider activity**
- `insider_transactions(id PK, accession_no FK, table_kind ('nonderiv'|'deriv'), row_no, issuer_cik, owner_group text, security_title, transaction_date, deemed_execution_date, code, equity_swap, shares, price, value_usd, acquired_disposed, shares_owned_after, direct_indirect, nature_of_ownership, plan_10b5_1 ('flag'|'footnote'|'none'), exercise_price, exercise_date, expiration_date, underlying_title, underlying_shares, footnotes jsonb, superseded_by NULL, flags text[])`, unique on `(accession_no, table_kind, row_no)`
- `insider_holdings(accession_no, table_kind, row_no, issuer_cik, owner_group, security_title, shares_owned, direct_indirect, nature_of_ownership, derivative fields…, superseded_by)`
- `form144_notices(accession_no PK, filer_cik, issuer_cik, seller_name, relationship, security_class, broker, shares_to_sell, market_value_usd, shares_outstanding, approx_sale_date, exchange, acquired_how, acquired_date, plan_10b5_1_adopted NULL, matched_sale_accession NULL)`
- `ownership_stakes(accession_no PK, form_type, issuer_cik, cusip, event_date, amendment_no, is_activist, percent_of_class, shares, reporting_persons jsonb, purpose_excerpt, is_current)`

**Funds**
- `fund_managers(cik PK, name, is_tracked, tracked_reason, latest_period, latest_value_usd, latest_positions)`
- `fund_filings(accession_no PK, filer_cik, period_of_report, filed_date, accepted_at, submission_type, amendment_type, value_total_usd, entry_total, superseded)`
- `fund_positions(filer_cik, period, cusip, put_call ('' when none), shares, sh_prn, value_usd, weight, source_accessions text[])`, with PK `(filer_cik, period, cusip, put_call)`, range-partitioned by `period` per year. These are the effective holdings after amendments, with rows for the same CUSIP summed.
- `fund_position_changes(filer_cik, period, cusip, put_call, prev_shares, shares, change ('NEW'|'ADD'|'TRIM'|'EXIT'|'SAME'), shares_change_pct, value_usd, weight, prev_weight)`

**Prices**
- `prices_daily(symbol, date, open, high, low, close, volume, adj_close, source)`, with PK `(symbol, date)`

**Derived (rebuilt by analytics)**
- `decisions(id PK, owner_group, issuer_cik, direction ('buy'|'sell'), first_trade_date, last_trade_date, shares, value_usd, vwap, stake_change_pct, first_accession, accepted_at, plan_10b5_1, badges text[])`, with `decision_owners(decision_id, owner_cik)` linking each decision to its owners
- `decision_returns(decision_id, basis ('filed'|'executed'), horizon ('1m'|'3m'|'6m'|'12m'), entry_date, entry_price_adj, exit_date, raw_return, excess_spy, excess_qqq, excess_sector, is_complete, exit_reason ('horizon'|'last_price'))`
- `positions(owner_cik, issuer_cik, security_title, shares, direct_indirect, as_of_date, last_accession)`, holding the latest reported non-derivative holdings
- `profile_stats(kind ('insider'|'fund'), cik, basis, <summary metrics in 9.6>, updated_at)` and `profile_windows(kind, cik, basis, window ('ytd'|'1y'|'3y'|'5y'), ret, ret_spy, ret_qqq, ret_sector, annualized, vol, max_drawdown, beta, time_invested_pct)`
- `fund_nav_daily(cik, basis, date, nav, nav_spy, nav_qqq, nav_sector)`, for tracked funds only
- `feed_items(accession_no PK, accepted_at, form_type, issuer_cik, owner_group, owner_names, top_role, direction, value_usd, shares, price, plan_10b5_1, badges text[], market_cap_usd, sector)`, one row per filing for fast feed queries

**App and operations**
- `users(id PK, name)`, seeded with id 1
- `watchlists(id PK, user_id FK, name)` and `watchlist_items(watchlist_id, kind ('insider'|'company'|'fund'), cik, added_at)`
- `job_requests(id PK, kind, params jsonb, status ('requested'|'running'|'done'|'failed'), progress jsonb, error, requested_at, started_at, finished_at)`
- `ingest_runs(id PK, job, started_at, finished_at, fetched, new_rows, missed, errors, notes jsonb)`

Search uses `pg_trgm` indexes on owner, issuer and fund names, exact match on tickers, and numeric match on CIKs.

## 9. Analytics

### 9.1 Decisions

- **What counts:** only open-market purchases (code `P`) and sales (code `S`) are decisions. Grants (`A`), exercises (`M`), tax withholding (`F`), gifts (`G`), conversions and every other code stay in the transaction log and holdings but not in performance.
- **10b5-1 trades:** a trade is pre-planned if the filing's `aff10b5One` is set (`plan_10b5_1 = 'flag'`), or, for pre-2023 filings, a footnote on the row mentions "10b5-1" (`'footnote'`). Pre-planned trades are left out of performance by default. A `include_10b5_1` toggle on every analytics endpoint puts them back.
- **Superseded rows** are ignored.
- **Episodes:** trades by the same owner group in the same issuer and direction, each within 10 trading days of the previous one, form one decision.
  - Its executed price is the volume-weighted average of the first trade day's rows.
  - Its publication time is the first filing's acceptance.
  - Its size is the sum over the episode.
  - Stake change for buys = shares bought ÷ shares held before the first trade, using the owned-after figures.

### 9.2 Entry prices

Prices are compared on the adjusted scale: `adjusted = raw × adj_factor(date)`.

- **Executed basis:** the insider's own volume-weighted price on the first trade date, times that date's `adj_factor`. If the price is missing or zero, use that day's close and flag it.
- **Filed basis** (US Eastern, NYSE calendar), from `accepted_at`:
  - A trading day before 09:30 → that day's open.
  - A trading day from 09:30 to before 16:00 → that day's close.
  - At or after 16:00, or a non-trading day → the next trading day's open.
  - `accepted_at` unknown → treated as 16:00 on the filing date (so the next trading day's open), and flagged.

### 9.3 Per-decision returns

- **Horizons** are 1m, 3m, 6m and 12m, which means 21, 63, 126 and 252 trading days after the entry date. Each exits at that day's adjusted close.
- **Raw return** = exit ÷ entry − 1.
- **Excess return** = raw return minus the benchmark's return over the same entry-to-exit dates. The benchmarks are SPY, QQQ and the issuer's sector ETF. Sector excess is empty when the issuer has no sector or the ETF has no history for those dates (for example XLC before June 2018).
- **Sales** are scored with the sign flipped. A sale is right if the stock then does worse than the benchmark.
- **Incomplete horizons** are stored with `is_complete = false` and left out of averages.
- **Delisting:** if prices stop before the horizon, the decision exits at the last available close with `exit_reason = 'last_price'` and a flag.
- **Disclosure lag:**
  - The lag is the number of SEC business days from the trade to acceptance.
  - The lag cost is the price move between the executed and filed entry prices (filed ÷ executed − 1, sign flipped for sales). It shows how much of the move was gone before the public could act.

### 9.4 Insider copycat portfolio (per person, per basis)

This is a calendar-time portfolio, the standard method in insider-trading research.

- **Opening a lot:** each buy decision opens a lot with weight `w = 1` at its entry (9.2).
- **Partial sales:** a discretionary sale by the same person in the same issuer multiplies the weight by `(1 − fraction sold)`, where fraction sold = shares sold ÷ (shares sold + shares owned after). The sale takes effect at its own entry time on the same basis.
- **Closing a lot:** after 252 trading days, when `w < 0.05`, or at the last available price.
- **Daily return:** `r = (Σ wᵢ·rᵢ + max(0, 1 − Σ wᵢ)·r_SPY) / max(1, Σ wᵢ)`. At least one full position's worth is always invested, equal-weighted by `w`. Partial sales move money back into SPY. With no open lots, the portfolio earns SPY.
- **Windows:**
  - YTD runs from the previous year's last close.
  - 1y, 3y and 5y are trailing 252, 756 and 1260 trading days. 3y and 5y are also shown annualized.
- **Benchmarks** over the same window:
  - SPY and QQQ, bought and held.
  - A sector-matched portfolio: the same lots and weights, with each stock swapped for its sector ETF (SPY where there's no sector).
- **Risk:** annualized volatility, maximum drawdown, beta against SPY, and time invested %.
- **Equity curves** are computed on demand by the API with an LRU cache. `profile_windows` stores the window numbers.

### 9.5 Fund copycat portfolio (tracked funds, per basis)

- **Holdings:** each period's effective positions are held from their start until the next period's start.
  - The executed basis starts at the close of the quarter-end date (or the last trading day before it).
  - The filed basis starts at the 9.2 entry after the filing's acceptance.
- **Weights:** reported value ÷ total priced value, bought and held within the period.
- **Exclusions:** put and call rows, and unmapped or unpriced CUSIPs, are left out and the weights renormalized. The priced-value coverage % shows next to every number.
- **Windows, benchmarks and risk** work as in 9.4. The sector-matched benchmark swaps each holding for its sector ETF.
- **Storage:** `fund_nav_daily` stores the curves.
- **Tracked funds** are the curated `reference/tracked_funds.csv` (about 50 well-known managers, editable) plus the top `TRACKED_FUNDS_TOP_N` (default 500) filers by latest value that report at most 300 positions (that is, active managers). Every other filer still gets positions, changes and a place on company pages.

### 9.6 Profile stats and reliability rating

These are computed per insider (over decisions where they're an owner) and per tracked fund, on both bases. The filed basis is the headline number.

- **Counts:**
  - Insiders: decisions, buys, sells, and complete decisions (6m horizon complete).
  - Funds: quarters with a complete next quarter.
- **Avg ROI** is the mean 6m excess return against SPY over complete decisions, with the raw mean and median shown alongside. The horizon can be switched in the UI.
- **Hit rate** is the share of complete decisions with positive 6m excess.
- **Best and worst** decisions, by 6m excess.
- **Average lag and lag cost** (insiders).
- **Reliability rating:**
  - Shrunk mean: `(n·x̄ + k·μ) / (n + k)`. For insiders, `x̄` is the person's mean 6m filed-basis excess, `n` their complete decisions, `k = 5`, and `μ` the population mean with each decision counted once.
  - For funds, `x̄` is the mean quarterly filed-basis excess of the copycat against SPY, `n` is quarters and `k = 4`.
  - The shrunk mean is turned into a percentile (0–100) among profiles of the same kind with `n ≥ 1`.
  - Confidence label, insiders: Low under 5 decisions, Medium 5–15, High over 15.
  - Confidence label, funds: Low under 4 quarters, Medium 4–12, High over 12.
- **Risk label:** from 5-year (or full-history) annualized copycat volatility. Low is under 20%, Medium is 20–40%, High is over 40%.

### 9.7 Allocation, concentration, conviction

- **Insider allocation:** current value is the latest reported non-derivative shares times the latest close, grouped by issuer and by sector. Derivative holdings are listed but not valued.
- **Fund allocation:** the latest period's positions, grouped by position and by sector.
- **Concentration:** effective number of positions is `1 / Σ wᵢ²` by value. Also the top-5 weight share.
- **High conviction:**
  - Insiders: buy decisions with a stake change of 20% or more, or $1M or more.
  - Funds: positions at 5% or more of the portfolio, and `NEW` positions that enter the top 20.

### 9.8 Badges

| Badge | Rule |
|---|---|
| `cluster_buy` | 3 or more distinct owner groups make discretionary `P` decisions in the same issuer with first trade dates within 14 calendar days. The badge goes on each member decision, and the company page gets a cluster event. |
| `late_filing` | Acceptance is on or after the 3rd SEC business day after the transaction date (or the deemed execution date). Section 16 requires filing within 2 business days. |
| `first_buy_2y` | The owner group has no discretionary `P` in this issuer in the prior 24 months. |
| `dip_buy` | The adjusted close fell 20% or more over the 60 trading days before the first trade date. |
| `big_stake` | The buy's stake change is 20% or more, or its value is $1M or more. |
| `form144_matched` | A Form 4 `S` by the same person and issuer within 90 days after a Form 144's filing date links both records. The sale is labeled "pre-announced by Form 144" and the notice "sale executed". |
| `top_exec` | The owner holds a CEO, CFO or President role at that issuer (9.9). |

### 9.9 Role normalization

`officer_title` text is mapped by case-insensitive rules (for example "chief executive", "ceo", "principal executive" → CEO) onto `CEO`, `CFO`, `COO`, `President`, `Chair`, `General Counsel`, `Other officer`. Director, 10% owner and other flags are added. A person can hold several roles. The rules live in `analytics/roles.py` and are tested against real title strings from fixtures.

### 9.10 Recompute

- `analytics_full` rebuilds `decisions`, `decision_returns`, `positions`, badges, `profile_stats`, `profile_windows`, `fund_position_changes` and `fund_nav_daily` in dependency order. Tables are rebuilt into staging and then swapped, so readers never see half-built data.
- `analytics_incremental` recomputes only the issuers and owners touched by new filings.
- Population means for ratings are refreshed nightly.
- **Performance targets:**
  - The nightly full run takes under 30 minutes on the user's Mac.
  - The API computes an insider equity curve in under 300 ms.

## 10. API

These are JSON endpoints under `/api`. List endpoints take `cursor` and `limit` and support `format=csv`. Analytics endpoints take `basis=filed|executed` and `include_10b5_1`. The OpenAPI document at `/api/openapi.json` generates the frontend's TypeScript types (`openapi-typescript`).

| Endpoint | Returns |
|---|---|
| `GET /feed` | Paged `feed_items`. Filters: forms, direction, codes, roles, sectors, min/max value, min/max market cap, 10b5-1 include/exclude, badges, trade and filed date ranges, max lag days. |
| `GET /feed/summary?date=` | Counts by form, the biggest buys and sells, clusters, and late filings for the day. |
| `GET /insiders/{cik}` | Header: name, roles by company, rating, confidence, Avg ROI, hit rate, lag stats, and fund cross-link when the same CIK files 13F. |
| `GET /insiders/{cik}/decisions` | Decisions with returns for every horizon and basis, and badges. |
| `GET /insiders/{cik}/transactions` | The full transaction log, all codes included, with an SEC link per row. |
| `GET /insiders/{cik}/performance` | Equity curve, windows, benchmarks, risk. |
| `GET /insiders/{cik}/holdings` | Positions, allocation by issuer and sector, concentration. |
| `GET /insiders/{cik}/form144` | Form 144 notices with match status. |
| `GET /companies/{cik_or_ticker}` | Header: name, ticker, sector, market cap, latest price, and net insider buying over 3, 6 and 12 months. |
| `GET /companies/{cik}/prices` | OHLC bars plus markers (decisions, Form 144, 13D/G, cluster events). |
| `GET /companies/{cik}/insiders` | Roster with roles, last trade, net buying, and ratings. |
| `GET /companies/{cik}/institutions?period=` | 13F holders and their quarter-over-quarter changes. |
| `GET /companies/{cik}/stakes` | 13D/13G history, with current stakes. |
| `GET /companies/{cik}/form144` | Pending and matched notices. |
| `GET /funds/{cik}` | Header: name, value over time, positions count, rating, coverage. |
| `GET /funds/{cik}/holdings?period=` | Positions with changes, allocation, concentration, conviction. |
| `GET /funds/{cik}/performance` | Equity curve, windows, benchmarks, risk (tracked funds). |
| `GET /screener/insiders`, `GET /screener/funds` | Ranked lists. Filters: role, sector, min decisions, last trade date range, rating, confidence, window return ranges, risk label. Any column can be the sort key. |
| `GET /compare?ids=insider:123,fund:456,…` | Up to 4 profiles: summary stats, windows, normalized curves, allocation. |
| `GET /search?q=` | People, companies and funds, grouped by kind. |
| `GET/POST/DELETE /watchlists…` | Watchlists and items (user 1). |
| `GET /watchlists/{id}/activity` | Feed items for the entities on the watchlist. |
| `GET /health` | Job status, feed delay p50/p95, parse errors, backfill progress, coverage metrics. |
| `POST /jobs` | Queue a job request (backfill step, reparse, recompute). |

## 11. Dashboard

**Tech:**
- Vite, React, TypeScript and React Router.
- TanStack Query for data, and TanStack Table for dense tables with virtualization.
- Tailwind CSS and shadcn/ui.
- TradingView Lightweight Charts for price, equity and value-over-time charts. Recharts for allocation donuts and bars.
- Light and dark themes, a dense data-first layout, and `⌘K` search.

**Pages:**

1. **Live feed (`/`)**
   - Filters as in the `/feed` endpoint, saved in the URL.
   - Rows show form, time accepted, company, owner(s), role, direction, value, price, badges, and a link to the SEC source.
   - Auto-refreshes every 30 s, with a "new filings" indicator.
   - A daily summary strip across the top.
2. **Insider profile (`/insider/:cik`)**
   - Header: rating and confidence, Avg ROI, hit rate, lag cost, and a watch button.
   - Performance chart against SPY, QQQ and the sector benchmark, with a filed/executed toggle.
   - Windows table.
   - Decisions table, full transaction log, holdings with allocation donut, and Form 144 notices.
3. **Company page (`/company/:ticker`)**
   - Price chart with markers for buys, sells, Form 144, 13D/G and clusters.
   - Insider roster.
   - Institutional holders and their changes, with a quarter selector.
   - Stakes, and pending Form 144 sales.
4. **Fund page (`/fund/:cik`)**
   - Value over time.
   - Holdings with change chips (NEW, ADD, TRIM, EXIT), with a quarter selector.
   - Sector allocation, concentration, conviction, and performance with coverage %.
5. **Screener (`/screener`)**: tabs for insiders and funds, filters, sortable leaderboards, and CSV export.
6. **Compare (`/compare`)**: up to 4 profiles, with overlaid normalized curves and side-by-side stats and allocation.
7. **Watchlists (`/watchlists`)**: lists, items, and an activity feed.
8. **Data health (`/health`)**
   - Job table.
   - Feed delay p50/p95.
   - Recent parse errors, with a reparse button.
   - Backfill progress bars.
   - Coverage: sector map, CUSIP map, and decisions with prices.

Every number that comes from a filing links to that filing on sec.gov. The footer reads "Data from SEC EDGAR. Not investment advice."

## 12. Errors, observability, security

- **Errors:**
  - HTTP errors follow 7.1.
  - A parse failure sets `parse_status = 'error'` and stores the message. The worker moves on, and `signals reparse --status error` retries after a fix.
  - Each filing is normalized in its own transaction, so it either lands fully or not at all.
  - A missing price gives an empty return with a stated reason. Nothing is made up.
- **Logs:** structured JSON logs to stdout, plus an `ingest_runs` row per job run.
- **Health signals** on `/health`:
  - The live poll's last success time, with a warning if there's no filing for 30 minutes during 06:00–22:00 on a business day.
  - Feed delay percentiles.
  - Unresolved parse errors.
  - Coverage metrics.
- **Security:**
  - `.env` is never committed, and `.env.example` lists every key.
  - The database, API and web ports bind to 127.0.0.1 only, because v1 has no login.
  - Secrets never appear in logs.

## 13. Testing

- **Approach:** test-driven development throughout. `pytest` (with `pytest-asyncio`) for the backend, and Vitest with Testing Library for the frontend.
- **Fixtures:** real EDGAR filings saved by `scripts/record_fixture.py <accession>`:
  - A Form 4 open-market buy (single owner).
  - A Form 4 joint filing (several owners).
  - A Form 4/A with its original.
  - A Form 4 with the 10b5-1 checkbox, and a pre-2023 Form 4 with a 10b5-1 footnote.
  - A Form 4 with a derivative exercise and a same-day sale.
  - A Form 4 with a footnote-only price.
  - A Form 3 and a Form 5.
  - A Form 144.
  - A small 13F-HR, a 13F-HR/A restatement, and a pre-2023 13F with values in thousands.
  - A SCHEDULE 13D and a SCHEDULE 13G.
  - Two Atom feed pages, one daily index file, and 50-row slices of each bulk data set table.
  - A `submissions.zip` sample entry.
- **Parser tests:** golden files. Each fixture parses to an expected JSON document checked into the repo.
- **Analytics tests:** synthetic price series with hand-computed answers. They cover:
  - Entry timing: pre-open, intraday, after-hours, holiday, and unknown acceptance.
  - Split adjustment.
  - Delisting exit.
  - Episode grouping.
  - Partial sales in the copycat.
  - Shrinkage math.
  - Each badge rule.
  - 13F restatement versus new holdings.
  - Unit normalization in thousands versus dollars.
- **Integration tests:** API and normalization tests run against a real Postgres test database (the Compose `db` with a separate database name). No mocks for the database.
- **End to end:** a Playwright smoke test opens every route against a seeded database and checks for data and no console errors.
- **Static checks:** `ruff`, `pyright`, `tsc --noEmit`, `eslint`.
- **Commands** (recorded in `CLAUDE.md`): `uv run pytest`, `uv run ruff check`, `uv run pyright`, `npm test`, `npm run build`, `npx playwright test`.

## 14. Build approach

1. **Foundation, built by the main agent, in order:**
   - Repo, Compose and config.
   - All SQLAlchemy models and the first migration (the full schema in section 8).
   - The SEC client with the rate limiter and raw archive, and the SGML reader.
   - The fixture recorder and recorded fixtures.
   - The job table and worker skeleton.
   - The API skeleton, with every response schema and route stub, so the OpenAPI contract is complete.
   - The frontend skeleton, with types generated from that contract.
   - `CLAUDE.md`.
2. **Six subagents in parallel, each in its own git worktree, test-first:**
   1. Insider ingestion: parsers for Forms 3/4/5 and 144, live poll, reconcile, `bulk_345`, gap fill, amendments and joint filings.
   2. Fund and stake ingestion: 13F parser, `bulk_13f`, gap fill, CUSIP mapping, position changes, 13D/13G parser.
   3. Reference data and prices: `submissions.zip`, tickers, SIC-to-sector map, shares outstanding, Alpaca and yfinance providers, price loader, trading calendar.
   4. Analytics: everything in section 9, built against seeded test data.
   5. API: every endpoint in section 10, built against seeded test data.
   6. Frontend: every page in section 11, built against the typed contract with mock data until the API lands.
3. **Integration, by the main agent:** merge the branches, run the real backfill, run the spot checks and the Playwright smoke test, fix integration bugs, and do a final code review.

## 15. Later sub-projects (from the requirements)

- **2. Signals & alerts:**
  - Scoring rules for insider decisions, tuned on the backfilled returns.
  - Outperformer flags over rolling windows.
  - Real-time alerts through Telegram, Discord, Slack, email and SMS.
  - Custom alerts on watchlists and groups.
  - Instant versus digest delivery.
- **3. Congress:**
  - STOCK Act PTR ingestion from the House Clerk and Senate eFD sites, or Quiver. Amount ranges use the midpoint, labeled as an estimate.
  - Committee assignments (unitedstates/congress-legislators) and a map from committee jurisdiction to sector ("what they control").
  - Bills and hearings (Congress.gov API).
  - Member portfolios and outperformers, legislative-trade correlation, chamber and committee filters, and late-disclosure (over 45 days) flags.
- **4. Senior officials:**
  - OGE 278e annual reports and 278-T transaction reports (PDF parsing).
  - Federal judges' disclosures (CourtListener API).
  - Snapshot comparison over time.
  - Later, UK and EU registers of interests.
- **5. Research lab:**
  - Edge score: performance, timing, position size and event overlap.
  - Historical signal simulation: the P/L of following people or groups by rule.
  - Event correlation with 8-K events, earnings and news.
  - Options chains and options ideas: calls, puts and LEAPS on high-conviction decisions. These are informational only, behind a legal review before any public release.

## 16. Prerequisites, risks, open checks

**Needed from the user before the build**

- Docker Desktop running.
- An SEC contact (name and email) for `SEC_USER_AGENT`. SEC requires it.
- Optional: a free Alpaca API key and secret (otherwise yfinance only), and a free OpenFIGI key for faster CUSIP mapping.
- About 25 GB of free disk.

**Risks and how they're handled**

| Risk | Handling |
|---|---|
| The `acceptanceDateTime` format or timezone in `submissions.zip` differs from the `.txt` header | Checked against `<ACCEPTANCE-DATETIME>` on the fixtures before the backfill. Parsing follows what the check finds. |
| Alpaca lacks delisted symbols (survivorship bias) | yfinance fallback, plus a last-price exit. Data health shows the share of decisions with no prices. If it's above 5%, a one-off delisted-price purchase (for example EODHD) is proposed. |
| OpenFIGI limits are lower than expected | Batched, resumable, with an optional key. The name-match fallback covers the rest, and coverage shows on Data health. |
| The Mac sleeps, so the live feed has gaps | The nightly reconcile fills them. The feed is only real-time while the worker is awake. A later move to a server uses the same Compose file. |
| SEC blocks traffic | The User-Agent is required, the rate is capped at 8/s, and a 403 triggers a pause (7.1). |
| The first backfill is long | Bulk loads take about an hour. Per-filing gap fills take about 9 hours at 8/s. It's resumable and runs overnight, with progress on Data health. |
| The SIC-to-sector mapping is approximate | It's a versioned CSV with tests. Coverage and "unmapped" counts show on Data health. |

**Checks folded into the build** (none of these change the design)

- Exact XML element names for each form, confirmed against the SEC technical specifications and the recorded fixtures.
- The 10b5-1 column name in the Insider Transactions Data Sets readme.
- The 13F data set value units, confirmed against the Form 13F readme.
