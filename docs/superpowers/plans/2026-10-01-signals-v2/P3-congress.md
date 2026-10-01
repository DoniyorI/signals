# P3: Congress trades

- **Goal:** House and Senate periodic transaction reports (PTRs) from 2016 on, cover to cover:
  - parsed, archived and mapped to issuers
  - analyzed like insiders, with point-in-time edge and both bases
  - placed in context with each member's committees
  - shown on Today, Stock, Person, Leaderboards and Signals
- **Branch:** `v2/p3-congress` from `main`, after P1.1–P1.4. It can run in parallel with P2. **Ledger:** `docs/superpowers/ledgers/v2-p3.md`.
- **Spec:** v2 spec §6. Follow the legal note (§6.5): every Congress number links to its source document, and nothing is used commercially without legal advice.

## Review Focus

1. **Wrong-company mapping.** A reported "ticker" can be a fund, a bond, a crypto asset or a typo. Map only with evidence, keep the rest unmapped, and show them as such.
2. **Amount ranges treated as exact values.** Store min, max and midpoint, and always display the range.
3. **Duplicates from amended reports.** Supersede when an amendment names its original. Otherwise flag likely duplicates (same member, asset, date, type and amount range) and don't double-count them.
4. **Scanned or paper filings silently skipped.** They must be stored, counted and listed as `needs_review`.
5. **Bot blocks or terms violations.** Use polite rate limits, a descriptive User-Agent, honor the Senate usage agreement, and archive everything.
6. **Committee overlap claimed historically.** v2 uses current assignments only, and the UI says so.

---

### Task P3.1: Verify sources and record fixtures (no parsers yet)

**Files:**
- `backend/tests/fixtures/congress/{house,senate,members}/…`
- `backend/tests/fixtures/congress/MANIFEST.json`, holding `expect` anchors read by hand from each document
- `scripts/record_congress_fixtures.py`

**Verify and record:**
- **House:**
  - The yearly index ZIP: expected at `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip`, holding `<YEAR>FD.xml` with each member's Prefix, Last, First, Suffix, FilingType, StateDst, Year, FilingDate and DocID.
  - PTR PDFs: expected at `.../public_disc/ptr-pdfs/<YEAR>/<DocID>.pdf`.
  - Record:
    - one index trimmed to about 60 entries, including PTRs (FilingType P) and amendments
    - three electronic PTR PDFs: one with many rows, one with spouse/joint owners, one with options or a partial sale
    - one scanned PTR
- **Senate (eFD):**
  - The usage-agreement form and the report-search JSON for PTRs.
  - Record:
    - one search response, trimmed
    - two electronic PTR HTML pages
    - one paper PTR page
- **Members and committees:** from the public-domain `unitedstates/congress-legislators` data: current and historical legislators (trimmed), current committees, and current committee membership.

**Rules:**
- Record the real URL patterns. If they differ from the expected ones above, the real ones win; record a ruling.
- Use a `CONGRESS_USER_AGENT` setting in `.env`. **Ask the user before putting their name or email in it** (their SEC contact was approved for sec.gov only). Default: `Signals/1.0 (personal research)`.
- Keep to at most 2 requests per second per host.

**Commit:** `test(congress): recorded House, Senate and legislator fixtures`

### Task P3.2: Members, committees and the committee-to-sector map

**Files:**
- `backend/migrations/versions/v2_p3_members.py`
- `backend/src/signals/congress/members.py`
- `backend/src/signals/reference/committee_sectors.csv` (curated)
- tests

**Tables:**
- **`members`:**
  - `bioguide_id` PK
  - name, chamber, state, district, party
  - first and last term dates
- **`committees`:** code PK, name, chamber, parent code (for subcommittees)
- **`committee_memberships`:**
  - `bioguide_id`, `committee_code`
  - role (member, chair or ranking)
  - `source`, `as_of`
- **`committee_sectors`:**
  - `committee_code`, `sector` (one of v1's sector names), `weight` (0–1)
  - `rationale`

**The curated CSV:**
- Covers every current standing committee in both chambers.
- Each row gets a one-line rationale. For example: House Financial Services → Financials (1.0).

**USER GATE:** show the user the CSV, and have Claude review it before it's used in badges.

**Job:** `members_refresh`, weekly, Sunday 05:30 ET.

**Tests (write first):**
- `test_members_loaded_by_bioguide`
- `test_memberships_include_roles`
- `test_every_current_committee_has_a_sector_row_or_explicit_none`
- `test_refresh_idempotent`

**Commit:** `feat(congress): members, committees and sector map`

### Task P3.3: House PTR ingestion

**Files:**
- `backend/migrations/versions/v2_p3_ptr.py`: `ptr_filings` and `ptr_transactions`, per spec §6.2
- `backend/src/signals/congress/house.py`
- `backend/src/signals/congress/parsers/house_ptr.py`
- tests and golden JSON

**Dependency.** PDF text and table extraction needs `pdfplumber`, pinned to an exact version (MIT license). Record it in the ledger. There is no OCR in v2: scanned PDFs are stored with `needs_review=true`.

**Flow:**
1. Fetch the yearly index and raw-archive it.
2. Create a `ptr_filings` row for every PTR.
3. Fetch each new PDF and archive it.
4. Parse it into rows.
5. Store `parse_status`. On failure, write `parse_error`; never drop the filing.

**Fields to parse:**
- owner code: self, SP (spouse), JT (joint) or DC (dependent child)
- asset name, plus the ticker in parentheses when present
- asset type code, such as ST, OP or OT
- transaction type: purchase, sale, partial sale or exchange
- transaction date and notification date
- the amount range, for example "$1,001 - $15,000" becomes min 1001 and max 15000; "Over $50,000,000" becomes min 50,000,001 and max null
- the cap-gains-over-$200 flag
- the description or comment

**Tests (write first):**
- `test_index_lists_ptrs_with_docids`
- `test_electronic_ptr_rows_match_golden`: three fixtures
- `test_amount_range_parsing_including_open_ended`
- `test_scanned_ptr_marked_needs_review_not_dropped`
- `test_reparse_from_archive_matches`

**Commit:** `feat(congress): House PTR ingestion`

### Task P3.4: Senate PTR ingestion

**Files:**
- `backend/src/signals/congress/senate.py`
- `backend/src/signals/congress/parsers/senate_ptr.py`
- tests

**Flow:**
1. Run the agreement and CSRF session flow.
2. Run the report search for PTRs in date windows, paginated.
3. Parse the electronic PTR HTML tables into the same row shape as the House parser.
4. Store paper PTRs with `needs_review`.
5. Archive everything.

**Tests (write first):**
- `test_search_pages_until_exhausted`
- `test_electronic_ptr_rows_match_golden`
- `test_paper_ptr_needs_review`
- `test_session_reestablished_after_expiry`

**Commit:** `feat(congress): Senate PTR ingestion`

### Task P3.5: Normalization, issuer mapping and amendments

**Files:**
- `backend/src/signals/congress/normalize.py`
- tests

**Issuer mapping:**
1. Look up the reported ticker with `signals.domain.tickers.issuer_for_symbol`, as of the transaction date.
2. Otherwise, use a pg_trgm name match to `issuers.name` with similarity ≥ 0.6 and the same asset type, stocks only.
3. Otherwise, leave it unmapped and keep it.

Store `map_method` and `map_confidence`.

**Amendments:**
- An amendment that names its original supersedes it.
- Otherwise, flag likely duplicates (same member, asset, date, type and range) and exclude them from analytics.

**Feed:** create feed items for member trades, so they appear in All filings with their source link.

**Tests (write first):**
- `test_ticker_mapped_as_of_trade_date`
- `test_name_match_threshold_and_stock_only`
- `test_unmapped_kept_and_counted`
- `test_amendment_supersedes_original`
- `test_likely_duplicate_flagged_and_excluded`

**Commit:** `feat(congress): normalize trades and map issuers`

### Task P3.6: Analytics for members

**Files:**
- `backend/src/signals/analytics/` (extend `decisions`, `entries`, `badges` and `signals` for actor kind `member`)
- a migration adding `decisions.value_min` and `decisions.value_max` (nullable)
- tests

**Decisions:**
- Same episode rules as insiders: same member, issuer and direction within 10 trading days.
- Owner group is `member:<bioguide_id>`.
- `value_usd` is the sum of the range midpoints, with min and max sums kept.

**Bases:**
- **Filed:** the next session's open after `filed_date`. PTRs have no acceptance time, so treat them as after the close.
- **Executed:** the close on the transaction date.
- Record both as rulings.

**Badges:**
- `late_filing`: more than 45 days from the transaction to the filing
- `committee_overlap`: the issuer's sector carries weight ≥ 0.5 for any of the member's current committees
- `spouse_trade`
- `member_cluster`: at least 2 members, same issuer and direction, within 10 trading days

**Edge and score:**
- PIT edge for kind `member`, from P2.1.
- The signal score for members uses v0-style rules (P1.3) plus edge percentile, committee overlap (+8) and member cluster. Don't apply the insider-trained v1 model to members. Record a ruling.
- Add the Congress preset (top-decile members' buys) to P2's presets.

**Tests (write first):**
- `test_member_episode_grouping`
- `test_range_midpoint_and_bounds`
- `test_filed_basis_next_open_after_filed_date`
- `test_late_filing_45_days`
- `test_committee_overlap_uses_sector_weight`
- `test_member_edge_no_lookahead`

**Commit:** `feat(analytics): Congress decisions, returns, badges and edge`

### Task P3.7: Congress API

**Endpoints:**
- `GET /api/members?q=` and `GET /api/members/{bioguide}`
- `GET /api/members/{bioguide}/summary`
- `GET /api/members/{bioguide}/trades`, paged, with CSV export
- `GET /api/members/{bioguide}/power`:
  - the share of trade value in overseen sectors against the member's overall mix and against all members
  - the overlapping trades
- `GET /api/congress/feed`
- `kind=members` on leaderboards
- members in the company-summary markers
- Home's `congress` section and `actor_kind=member` on signals
- Regenerate the OpenAPI document and the types, and update the mocks.

**Tests:**
- `test_member_summary_and_ranges`
- `test_power_shares`
- `test_leaderboard_members`
- `test_home_congress_section`
- `test_company_markers_include_members`

**Commit:** `feat(api): Congress endpoints`

### Task P3.8: Congress UI

**Person page for members:**
- party, state and chamber
- committee chips, labeled "current committees"
- trades shown with their ranges
- a power-versus-holdings chart: the member's share of trading in overseen sectors, against their own mix and against all members

**Elsewhere:**
- **Today:** a Congress section.
- **Stock page:** a Congress tab, plus member markers on the chart.
- **Leaderboards:** a Congress tab.
- **Footer:** becomes "Data from SEC EDGAR, the House Clerk and the U.S. Senate. Not investment advice."

**Tests:**
- `ranges never shown as exact amounts`
- `needs-review trades listed with source link`
- `committee chips labelled current`
- `stock page congress markers`

**Commit:** `feat(web): Congress pages and sections`

### Task P3.9: Jobs, backfill and completeness

**Jobs:**
- `congress_backfill`: House yearly indexes and Senate search by month, from 2016 on; resumable.
- `congress_daily`: 07:00 ET on business days, and included in the catch-up order.
- `members_refresh`: weekly.

**Completeness report** (P0.2), additions:
- House index PTR counts against stored PTRs
- Senate search counts against stored PTRs
- the `needs_review` count and the unmapped share

**Data health** lists the `needs_review` filings, with their source links.

**Tests:**
- `test_backfill_resumes`
- `test_daily_picks_up_new_filings_once`
- `test_completeness_counts_congress`

**Commit:** `feat(congress): jobs, backfill and completeness`

**Phase end:** run the backfill and record the numbers in the report: filings, rows, parsed %, mapped %, `needs_review`. Then request Claude's review.
