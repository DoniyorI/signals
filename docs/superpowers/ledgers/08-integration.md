# Integration continuation — 2026-09-30
Task I1: Ruling: user authorizes up to three concurrent subagents, overriding the original plan's already-spent agent cap — explicit continuation instruction — cost if wrong: coordination overhead; disjoint files and parent-owned commits.
Task I1: Ruling: merge completed C/A/B/D/E branches in prescribed order while independent F9–F13 work finishes in its existing worktree; merge F last — prepares merged backend tests without changing dependency order — cost if wrong: partial integration exists until F is validated and merged.
Task I1: Ruling: production bootstrap, job recovery, price correction, and health observability need regression-backed fixes before any live backfill — read-only audit reproduced missing registry and oversized price statement, and traced checkpoint/health gaps — cost if wrong: additional validation time rather than risking a falsely successful historical run.
Task I1: baseline: C/A/B/D/E merged cleanly; bash scripts/setup-venv.sh exit 0; uv run pytest -q exit 0 against throwaway PostgreSQL; full evidence in merged-backend-baseline.log. F merge and cross-workstream test remain pending.
Task I1-readiness: complete (commits 92474d3..1a34901, tests: dedicated RED → GREEN; full uv run pytest -q, ruff check, pyright, OpenAPI drift → exit 0; singleton, all interrupted requests, gap retries, acceptance repair, scheduled/requested diagnostics and committed feed timing covered)
Task I1-prices: complete (commits 1a34901..4eb29a9, tests: 34 focused price tests RED → GREEN; full merged pytest, ruff and pyright → exit 0)
Task I1-sorting: complete (commits 4eb29a9..86677bc, tests: 23 backend sort tests RED → GREEN; frontend column-controls RED → GREEN, 112 full tests; build/lint → exit 0)
Task I1-sorting: Ruling: names and sectors sort case-insensitively; roles sort their displayed comma-separated value, risk uses low/medium/high order, nulls last with CIK tie-break; company uses displayed current ticker or name; fund coverage matches displayed latest filed-basis NAV even on executed basis — sorting must agree with rendered metrics across pages — cost if wrong: sort labels may need additional UI help.
Task I1: Ruling: requested jobs must fail on explicit nonzero error/errors counters and preserve result details — no-silent-failure rule also applies to jobs returning partial results — cost if wrong: completed partial work still requires attention and an idempotent retry.
Task I1: Ruling: cross-workstream as_of is 2026-09-29, with independently seeded CUSIP reference mappings — recorded 13F sample reports June 2026 so original plan 2025-12-31 cannot have fund performance — cost if wrong: test as_of must remain later than fixture reporting/filing times.

## prices-report.md
# I1-price-readiness — implementation ready for parent review

Scope: only `backend/src/signals/prices/{loader,jobs}.py`, the isolated `test_price_readiness.py`, and the existing price loader tests whose old last+1 expectation changes to overlapping-bar refresh. No staging or commits. Parent owns final review, integration ledger and task commit. Original findings: `/private/tmp/signals-integration-audit.md`, findings 3 and 4.

## Final behavior

- Upserts use batches of at most 1,000 bars / 9,000 values, below the PostgreSQL 65,535 bind boundary. ON CONFLICT updates only changed values/source. Bounded RETURNING supplies actual inserted/changed counts because this environment reports rowcount=-1 without RETURNING. Identical reruns report rows=0 and preserve natural-key uniqueness.
- Provider responses are bounded to 25 symbols and 366 calendar days per call. Multi-year history is streamed as frames rather than aggregated into one huge dataframe.
- Every normal load probes the last stored bar even at the same requested end date. A changed raw close OR adjusted close triggers a complete refresh for that symbol. The extra raw-price comparison handles Yahoo's proportional raw/adjusted split revision that would leave adj_close/close unchanged.
- Newly earlier universe starts extend coverage. Durable `prices_history_starts` records the earliest completed request, so a provider's IPO/coverage floor does not cause a years-long missing prefix to be fetched every cron run.
- Durable `prices_history_ends` records the checked-through date. A delisted symbol with an old final bar probes that one sentinel and only new unchecked dates; it does not repeatedly fetch years of known-empty tail.
- Revision refreshes retain every stored bar and require the provider to return every stored date being refreshed. Partial responses raise a visible error and roll back. Successful revision history plus its new/overlapping bars commit together. Price jobs serialize bounded batches with a PostgreSQL advisory transaction lock to avoid overlapping daily/backfill writers consuming one another's revision sentinel.
- Both `prices_daily` and `backfill_prices` use this production path. Requested jobs accept `{"refresh_history": true}` to re-fetch history deliberately, including old vendor corrections that leave the latest sentinel unchanged and previously unavailable internal/tail prices. This option bypasses the checked-through optimization.
- Existing missing-symbol/fallback behavior and dated-symbol universe contracts are retained. Fallback prices run through the same sentinel, bounded-fetch, completeness and upsert handling.

## Rulings for the integration ledger

Task I1-price-readiness: Ruling: use latest stored raw/adjusted-close revision detection for automatic corporate-action refresh, plus an explicit refresh_history repair option — new splits/dividends affect a pre-event sentinel, including proportional Yahoo OHLC revisions, while arbitrary old corrections before an unchanged latest sentinel cannot be detected by a cheap daily probe — cost if wrong: an old vendor-only correction needs an explicit requested repair; detecting every arbitrary revision automatically would require periodic full history or a provider corporate-action revision feed outside the current protocol.

Task I1-price-readiness: Ruling: track completed requested price start and checked-through end in app_state — the first actual bar may follow the universe start and a delisted last bar may precede the run end by years; max(date) alone would repeatedly download those empty prefixes/tails — cost if wrong: previously unavailable dates within the checked span require refresh_history=true to revisit; no bar is invented and a newly earlier universe start still triggers coverage expansion.

Task I1-price-readiness: Ruling: serialize price batches and commit revisions with their sentinel after completeness checks — otherwise a fetch failure could update the newest bar but leave earlier history stale, and the next retry would see no sentinel change — cost if wrong: overlapping price jobs wait at batch boundaries, and a failed batch repeats up to 25 symbols' work. Network calls occur within that bounded batch transaction to preserve rollback safety.

Task I1-price-readiness: Ruling: LoadPricesResult.loaded remains the count of symbols queried, including sentinel checks; rows counts actual inserted or changed bars — the old C6 counter ruling describes attempted symbols, and idempotent checks now require a request even when no new date is needed — cost if wrong: a consumer expecting loaded to mean only symbols with newly appended bars must distinguish rows or inspect price dates.

## Test-first evidence and exit codes

All database cases use the real disposable PostgreSQL fixture and fake PriceProvider transport boundaries, never a mocked DB. Test settings explicitly disable env-file loading. The first sandbox command did not run tests because uv's external cache was denied (exit 2); subsequent checks used the authorized escalated uv commands.

1. RED: `uv run pytest tests/integration/test_price_readiness.py -q` -> exit 1, all 8 initial cases failed. Real psycopg rejected the 8,000-row / 72,000-parameter statement; old adjusted history remained stale after splits/dividends on both jobs; same-end rerun/earlier discovery failed. Full trace was very large, so later failures use --tb=short.
2. Bounded-write intermediate: `uv run pytest tests/integration/test_price_readiness.py -q --tb=short` -> exit 1, exposed rowcount=-1 and remaining history failures. Switched changed-row counting to bounded RETURNING. `uv run pytest tests/integration/test_price_readiness.py::test_large_price_upsert_stores_and_updates_8000_bars -q --tb=short` -> exit 0.
3. RED/ GREEN coverage floor: single `test_missing_prelisting_history_is_not_refetched_every_run` -> exit 1 (four multi-year calls instead of one sentinel call); combined loader/reference-price set after attempted-start checkpoint -> exit 0, 18 cases. The old incremental-start test was updated to assert overlapping last date; earlier coverage has its own independent test.
4. RED explicit repair: readiness set -> exit 1, only the two job_explicit_history_refresh cases failed when jobs omitted the repair flag; production flag forwarding fixed them.
5. RED/ GREEN completeness: parametrized `test_incomplete_full_refresh_rolls_back_mixed_adjustments` -> exit 1, both did-not-raise failures; after completeness checks, full scoped set -> exit 0, 31 cases.
6. RED/ GREEN delisted scale: `test_delisted_symbol_does_not_refetch_known_empty_tail` -> exit 1 (yearly windows to 2024); after checked-through range handling, scoped set -> exit 0, 32 cases.
7. RED/ GREEN explicit gap repair: `test_explicit_refresh_revisits_previously_empty_tail` -> exit 1 (2022 recovered bar missing); repair flag now bypasses checked-through spans, final pre-review scoped set -> exit 0, 33 cases.
8. RED independent review regression: `test_fallback_proportional_raw_and_adjusted_revision_refreshes_history` -> exit 1 (stored closes [100,50,50] instead of [50,50,50]). Automatic comparison now checks raw close and adjusted close independently.
9. Final GREEN command: `uv run ruff format src/signals/prices/loader.py src/signals/prices/jobs.py tests/integration/test_price_readiness.py tests/integration/test_price_loader.py && uv run ruff check src/signals/prices/loader.py src/signals/prices/jobs.py tests/integration/test_price_readiness.py tests/integration/test_price_loader.py && uv run pyright src/signals/prices/loader.py src/signals/prices/jobs.py tests/integration/test_price_readiness.py tests/integration/test_price_loader.py && uv run pytest tests/integration/test_price_readiness.py tests/integration/test_price_loader.py tests/integration/test_jobs_reference_prices.py tests/unit/test_alpaca_provider.py tests/unit/test_yfinance_provider.py -q --tb=short` -> combined exit 0; formatter clean after one file reformat, Ruff all checks passed, Pyright 0 errors/warnings, 34 tests passed.
10. `git diff --check -- backend/src/signals/prices/loader.py backend/src/signals/prices/jobs.py backend/tests/integration/test_price_loader.py backend/tests/integration/test_price_readiness.py` -> exit 0.

Meaningful recovery/fallback cases also verify: failed mid-history vendor fetch does not consume the old sentinel; retry repairs all older bars; unchanged symbols avoid full refresh; fallback provider handles adjusted-history refresh; full/earlier-history partial responses cannot commit mixed bases; same-end rerun checks revisions while unchanged writes remain zero.

Full merged suite is delegated to the parent's final integration checks. Parent explicitly requested no additional full-suite run while other integration edits/tests were active. A parallel agent's earlier full run reported 661 passing tests plus the deliberately active delisted-tail RED and a parent cross-fund test under correction; parent subsequently reported its cross-fund test green. Those earlier intermediate full-suite results are not a final suite verification claim.

## Limits

No real provider calls, live backfill, corporate-action feed, production timing/memory benchmark, or analytics performance measurement was performed. Detecting changes in old vendor history that do not alter the latest raw or adjusted close is intentionally an explicit repair operation. Provider omissions during a revision produce a visible job failure with rollback rather than a partly rebased price series. Final whole-suite and review remain the parent's responsibility before committing and starting live workers.


## health-report.md
# I1 health integration fixes

Ready for parent review/commit. No staging, commits, schema changes, secret reads, raw-data edits or real outside traffic.

## Scope

- `backend/src/signals/ingest/pipeline.py`: `parsed_at` now records failed handler attempts, including a new failed reparse after an old success.
- `backend/src/signals/worker.py`: scheduled jobs own an outer durable `track_run`; returned counters and per-day results populate fetched/new/missed/errors; diagnostic messages persist. Existing inner tracking reuses the same tracker through F10's ContextVar implementation. A session-level Postgres advisory lock on a dedicated connection guards the entire worker lifetime, before outside-client construction, bootstrap, recovery or scheduling. Worker startup calls F10's `recover_interrupted_requests(session)` and marks unfinished legacy IngestRun rows interrupted/error under this exclusive lock.
- `backend/src/signals/reference/jobs.py` (parent-authorized extension): propagate submissions errors; malformed ZIP members fail the job visibly and leave the submissions checkpoint unfinished for retry.
- `backend/src/signals/ingest/feed.py`: per-entry fetch/parse errors include accession-specific diagnostics in `PollResult.error_details`. Successful feed timing is sampled after the feed transaction commits and persisted on the filing; last successful poll timestamp uses completion time. F10 owns the adapter serializing error_details into the job result.
- `backend/src/signals/api/queries/health.py`: preserve both tracked error/exception note keys; exclude failed, skipped and invisible filings from latency; expose the five real nested backfill stages plus gap-fill checkpoint bars; honor saved checkpoint timestamps; normalize reference/dataset/analytics/price units without mixing units; latest failed job turns overall status to warn.
- `backend/tests/integration/test_health_observability.py`: 18 dedicated integration cases across the above behaviors, real Postgres and recorded/mock HTTP.
- `backend/tests/api/test_health_jobs.py`: parent-authorized fixture correction adds visible FeedItems to the original percentile test; the old fixture's four Filing-only rows should no longer count as successful feed availability.

## Red/green and checks

All commands were run from `backend/`, with exit codes enforced. `uv` needed sandbox escalation for its configured cache and local Postgres; the approved test runner used isolated throwaway test databases.

- Initial `uv run pytest tests/integration/test_health_observability.py` → exit 1, 12 failed as expected (missing/stale attempt time, absent run records/details, hidden nested checkpoints, inaccurate/overinclusive latency, missing diagnostics).
- After implementation, health + existing API tests → 15 passed / 1 failed: original percentile fixture had no FeedItems. After the authorized fixture correction, the original percentile expectation is valid again.
- Worker-startup regression separately → RED exit 1 (`running` remained unrecovered); recovery hookup → GREEN.
- `uv run pytest tests/integration/test_health_observability.py tests/api/test_health_jobs.py tests/integration/test_pipeline.py tests/integration/test_feed_poll.py tests/integration/test_jobs_reference_prices.py` → exit 0, 32 passed.
- `uv run pytest` → exit 0, 658 passed in 26.60 s before the last checkpoint regression and peers' further test additions.
- Strengthened the latency test with SQLAlchemy's real after-commit event: initial delay 20 s + fetch 40 s + handler 50 s + commit 15 s = measured 125 s, replacing poll-start's incorrect 20 s. Focused health/API → exit 0, 17 passed.
- Additional completed-quarter regression → RED exit 1 (`done` falsely displayed while gap parent running). Corrected substep status: completed quarter alone is insufficient evidence of completion.
- Latest full `uv run pytest` → exit 1, 661 passed / 2 failed while peer integration work continued: `test_cross_workstream.py::test_filing_to_api_end_to_end` (fund performance empty points), `test_price_readiness.py::test_delisted_symbol_does_not_refetch_known_empty_tail` (yearly refresh windows vs expected one-day old-history call). All 14 dedicated health cases pass. Parent and price owner notified.
- Scoped Ruff → exit 0, all checks passed. Full Ruff → exit 1 only for parent-owned `test_cross_workstream.py` import/long-line formatting at that snapshot.
- Scoped Pyright → exit 0, no errors/warnings. Latest full `uv run pyright` → exit 0, no errors/warnings after peer test fixes.
- Singleton follow-up RED: `uv run pytest tests/integration/test_health_observability.py -k 'worker_lock or interrupted_unfinished'` → exit 1, 3 failed (missing worker lock/interrupted-run recovery). Implemented dedicated-connection lock and startup record recovery; added main-level ordering regression so moving the lock after SEC-client construction/recovery cannot pass unnoticed.
- Latest affected suite: `uv run pytest tests/integration/test_health_observability.py tests/api/test_health_jobs.py tests/integration/test_request_recovery.py tests/integration/test_jobs.py tests/integration/test_feed_poll.py tests/integration/test_pipeline.py` → exit 0, 47 passed. Final dedicated health suite → exit 0, 18 passed. Final scoped Ruff/Pyright → exit 0, no errors/warnings. Parent owns final stable full-suite verification after peer work; no repeated full runs during their intentional RED intervals.

## Rulings

- I1: Ruling: `parsed_at` is last handler attempt time, success or failure — matches E's health warning contract without schema changes — cost if wrong: consumers requiring last successful parse need a separate field later.
- I1: Ruling: Scheduled wrapper owns one durable run; same-job inner tracking borrows it; returned counters use max versus aggregate nested results to avoid counting reused tracker values twice — preserves existing analytics/reconcile owners without duplicate rows — cost if wrong: unknown future return shapes require a new adapter.
- I1: Ruling: A reference submissions load with malformed members must fail and retain an incomplete checkpoint — aggregate counters cannot be discarded and failed units must be retryable — cost if wrong: a malformed vendor member halts the reference step until corrected/retried.
- I1: Ruling: Health warns while a job's latest status is failed/error — an operational failure must not coexist with an unqualified all-clear banner — cost if wrong: an obsolete failed job remains attention-worthy until a later successful run/request supersedes it.
- I1: Ruling: Parent backfill expands into actual stages and separately named gap substeps; offsets remain filing attempts, dataset counts remain datasets; absent totals remain null; one completed quarter never completes the whole substep — no invented percentages or mixed-unit progress — cost if wrong: old checkpoints without timestamp/total metadata show fallback dates and indeterminate bars.
- I1: Ruling: Live `first_seen_at` is successful committed feed availability, sampled immediately after the original transaction commits — acceptance-to-feed measurements include fetch/parse/commit rather than just discovery — cost if wrong: a short second transaction persists the measurement, and a crash between transactions can leave a visible item temporarily unsampled.
- I1: Ruling: The single-worker architecture is enforced with a database session advisory lock held on a dedicated connection for the full lifetime, explicitly unlocked before pooled connection return — duplicate processes must not create separate SEC limiters or recover live work — cost if wrong: a later distributed/multi-database deployment needs a different ownership model. Startup recovery occurs only after acquiring the lock. F10's parent-directed refinement requeues all stranded running requests, preserving params/progress; failed-backfill retry reuse remains separate.
- I1: Ruling: Existing unfinished IngestRun rows are marked interrupted, finished and error once at guarded startup — stranded observability records must not remain indefinitely ambiguous — cost if wrong: future lease-aware concurrent worker architectures need owner-specific recovery instead of this single-worker rule.

## Limits

No real live-feed, coverage, latency or performance success criterion was measured. Feed timing tests use recorded data and a controlled clock. Existing pre-fix first_seen timestamps cannot be reconstructed retrospectively; use new post-fix ingestion for I5 evidence. Gap bars show the current checkpoint offset, not a fabricated cumulative historical filing total; producers do not currently store such totals. Health's historical latest-per-kind queries remain unbounded as noted in the audit; no production performance assertion is made.

Read-only review of F10's requests/gap changes found no remaining unit-retry defect: attempted offsets stay monotonic, pending failures retry separately, quarters do not complete with unresolved failures, parent insider/fund jobs raise, and failed request retries require matching parameters. Concrete remaining cross-owner gap found by F10: requested jobs returning nonzero error counters (live_poll, reparse) can currently remain status=done because `run_request` only fails escaping exceptions. Forwarded to parent/F10 for authorization and test-first handling in jobs.py; this agent did not edit that file.


## requests-report.md
# Integration: handler startup, requests, gap fill, and fund acceptance

Ready for parent review/commits. No staging or commits performed. Addresses audit findings
1, 2, 5 and 10, plus the agreed tracker/checkpoint/PollResult interfaces consumed by the
health agent. No real network calls; SEC access in tests uses MockTransport and recorded
fixtures. No secrets or raw production archive files accessed.

## Changes

- `jobs.load_all_jobs()` registers all real ingestion handlers through an explicit
  repeatable `register_all_handlers()` bootstrap, including after registry resets.
- CLI reparse initializes handlers before processing archived filings.
- Identical requested/running resumable backfills reuse the existing request id. A failed
  backfill retry with the same kind and exact JSON params requeues that row and retains
  progress; differing params and unrelated failed jobs do not inherit its checkpoint.
- `recover_interrupted_requests(session) -> int` requeues every stranded running request,
  preserving params and checkpoints. The health agent calls it once during worker startup
  after acquiring an exclusive PostgreSQL advisory lock. Failed jobs are never recovered
  automatically; their retry reuse remains limited to matching resumable backfills.
- `track_run` uses a ContextVar to reuse the current tracker for nested tracking with the
  same job name; only the outer context records the row and escaping error. Different
  nested jobs still record their own run, and context state resets on all exits.
- `_save_progress` stamps root `updated_at`; backfill_all stamps child step metadata.
- Gap-fill offsets still count every attempted entry. A separate quarter-keyed
  `pending_failures` queue retains accession, CIK and typed diagnostic text. Resumption
  retries that queue without rewinding the scan offset. An unresolved quarter remains
  unfinished, and insider/fund job wrappers raise so backfill_all cannot finish the step.
- Fund acceptance repair now fills missing `fund_filings.accepted_at`, in addition to the
  canonical filing and feed. Analytics reads the repaired SEC filing instant and derives
  its acceptance_unknown flags accordingly; no schema changes.
- jobs_insider propagates `PollResult.error_details` as a JSON list for scheduled tracking.

## Files owned/changed

Production: backend/src/signals/jobs.py, cli.py, ingest/handlers/__init__.py,
ingest/gap_fill.py, ingest/jobs_insider.py, ingest/jobs_funds.py, ingest/bulk_345.py.

New dedicated tests: backend/tests/integration/test_request_recovery.py,
test_handler_bootstrap.py, test_gap_fill_recovery.py (16 tests).

Existing test updates: test_gap_fill.py now asserts its 450 mocked 404 failures retain
their final attempted offset and pending entries instead of falsely completing the
quarter; test_jobs_insider.py includes the new empty error_details list in successful
live_poll output.

## TDD and verification

Commands executed from backend/, with exit codes enforced:

- Initial dedicated test run via `uv run pytest -q tests/integration/test_request_recovery.py
  tests/integration/test_handler_bootstrap.py tests/integration/test_gap_fill_recovery.py`
  → exit 1, 15 failures. Recovery API absent, retry id/checkpoint lost, nested tracker
  duplicated, fresh interpreter registry empty, real Form 4/13F dispatch skipped,
  CLI skipped, gaps falsely completed, wrappers did not raise, and fund acceptance absent.
- The acceptance test initially had no holdings; added a position so real load_fund_inputs
  builds a book, then reran before implementation and observed the expected accepted_at=None
  failure. CLI also reran red with its expected skipped outcome.
- After implementation the same dedicated command → exit 0, 15 pass.
- PollResult diagnostic regression added → exit 1, KeyError(error_details); propagation
  implemented; subsequent affected run green.
- New + affected tests (request_recovery, handler_bootstrap, gap_fill_recovery, jobs,
  gap_fill, jobs_insider, jobs_funds, bulk_345, unit/test_cli) → exit 0, 49 pass.
- `uv run ruff format <owned files>` → exit 0.
- `uv run ruff check <owned files>` → exit 0.
- `uv run pyright` (whole backend, after test typing corrections) → exit 0,
  0 errors / warnings / informations.
- `git diff --check` → exit 0.
- Full `uv run pytest -q` → exit 1 at the concurrent parent-owned
  test_cross_workstream::test_filing_to_api_end_to_end: empty fund performance points,
  IndexError at its line 104; all other collected tests passed (661 collected in that run).
  Parent notified; must rerun full suite after its fixture correction.
- Full `uv run ruff check` initially → exit 1 only for the parent-owned in-progress
  test_cross_workstream.py's imports/long lines; parent notified and owns correction.

The initial sandboxed uv command could not access its existing uv cache; all subsequent
backend commands used approved require_escalated access to uv and local throwaway Postgres
databases. There was no auto-review rejection.

## Decisions for live ledger

Integration: Ruling: retry checkpoint reuse is limited to BACKFILL_STEPS/backfill_all and
exact matching params; active identical requests are never duplicated even when ordinary
coalescing is disabled — these are the documented resumable jobs, and cross-scope merging
would incorrectly skip work — cost if wrong: future resumable kinds need explicit inclusion.

Integration: Ruling (refined after parent review): startup recovery requeues every running
request only after the worker obtains its exclusive PostgreSQL advisory lock — all jobs
are idempotent per the spec, and leaving reparse/analytics requests running forever makes
them unrecoverable; exclusive ownership distinguishes interrupted work from active work —
cost if wrong: reruns can repeat idempotent work. The lock implementation belongs to the
health/worker agent. This supersedes the initial backfill-only recovery policy.

Integration: Ruling: failed historical gap entries retain attempted offsets plus a retry
queue, and errors block quarter and parent-step completion — honors the A9 attempted-offset
ruling while preventing permanent omissions — cost if wrong: a permanently bad SEC filing
blocks that backfill until repaired, which is explicit and health-visible rather than silent.

Integration: Ruling: acceptance_unknown is derived from a missing acceptance instant;
FundFiling has no separate acceptance_unknown column, so repair only its accepted_at and
let analytics recompute flags — avoids schema drift and verifies actual filed-target
behavior (same-day close for a known intraday acceptance) — cost if wrong: cached analytics
must be recomputed, which backfill_all already schedules in its final analytics step.

Integration: Ruling: preserve same-name nested run tracking through a ContextVar, stamping
only one durable outer row; stamp updated_at in JSON checkpoints without schema changes —
agreed with health agent to support scheduled visibility and checkpoint freshness — cost
if wrong: a caller that intentionally wanted distinct same-name nested records must use a
distinct job name.

Remaining limits: no real backfill/latency proof from these tests; recovery requires the
worker singleton guard; legacy already-completed checkpoints created before this fix
cannot identify forgotten failures and need an explicit rebuild if any exist.

Parent follow-up: parent reports its cross-workstream test now passes after seeding real
Security mappings for distinct CUSIPs; parent also formatted/fixed that test's lint.
Parent owns the final full-suite run once peer tasks stop changing.

Read-only peer review: health worker/error/checkpoint integration matches the interfaces
agreed above. Price loader review found an additional sentinel scenario: proportional
changes to both close and adj_close leave their ratio unchanged, so the current comparison
can miss a history rebase. Example: stored bars 100/100, revised last bar 50/50 and new
bar 50/50; earlier 100 history stays stale. Reported to parent and price agent, recommending
a regression plus sentinel-value comparison; no peer files changed.

Recovery refinement TDD: updated existing dedicated startup regression to include running
reparse and analytics_incremental with nonempty params/progress, alongside done and failed
requests. `uv run pytest -q tests/integration/test_request_recovery.py::test_exclusive_worker_startup_requeues_all_interrupted_requests`
→ exit 1 (recovered 2 instead of required 4). Broadened only the running-request filter.
Dedicated recovery/bootstrap/gap command → exit 0, 16 pass; owned refinement ruff check
→ exit 0. Parent owns subsequent full checks once singleton guard is complete.

Task I1: complete (commits 86677bc..9bf4383, tests: real SEC fixture cross-workstream parsers/prices/analytics/API and repeatability → GREEN; merged pytest, ruff, pyright, OpenAPI drift, one Alembic head → exit 0; frontend 112 tests, build/lint and mock Playwright 12 tests → exit 0)
Task I2: complete (commits 9bf4383..9bf4383, tests: docker compose up -d --build → exit 0; db healthy, migrate exited 0, api/worker/web running; /api/health status ok and sec_blocked_until null; real UI opened)
Task I3: started: request 3 backfill_all running, reference submissions ZIP downloaded 1.5 GB; initial feed parsed 472 filings, parse errors zero. No historical success threshold claimed.
Task I7: security preflight: Alpaca key/secret and SEC contact have zero matches in all tracked patches; raw git-log scan includes 94 SEC contact matches in author metadata, so use --format= to distinguish source leaks from intended Git author identity. No tracked .env/data, both ignored; all published ports bind 127.0.0.1. Values were never printed.
Task I7-pause: complete (commits 9bf4383..38a57ef, tests: persisted SEC pause bootstrap regression RED mocked HTTP 404 instead of SecBlockedError → GREEN; full pytest → 700 passed; ruff/pyright → exit 0)
Task I4: implementation committed (38a57ef..95dcc37), live historical validation pending. Unit/integration compare and deterministic year sample: initial RED 2 missing-script failures → 3 GREEN tests, scoped lint/type and full suite exit 0.
Task I4: Ruling: n=20 cannot include two from each of eleven years; take one per populated year then a second round while space remains — deterministic coverage of all years without exceeding sample size — cost if wrong: oldest-first second-round allocation may be replaced with an explicitly different sampling scheme.
Task I4: Ruling: manual script must hold the same worker advisory lock, so stop the scheduled worker before running it and restart afterward — two independent SEC limiters would violate the single-worker rule — cost if wrong: worker interruption, resumable jobs recover, latency needs a new continuous observation window. Script uses fresh SecClient fetches with RawArchive and never mutates parsed records.
Task I4/I6: Ruling: commit verified implementation before full historical data exists, keeping live criteria pending — multi-hour job must not leave tested code unrecorded; no success claim for unavailable evidence — cost if wrong: completion ledger needs a later evidence entry.
Task I6: configuration committed (95dcc37..a308356), full real-profile/performance checks pending. Mock Chromium 12/12, build/lint exit 0; real-stack feed/screener/watchlists/health/phone-root 5/5. Mock-specific identity interactions are skipped for real runs; all real profile routes still required.
Task F13 QA follow-up: offscreen Recharts lazy animation can appear blank in full-page screenshots; scrolled allocation charts inspected and render correct 100%/62%/38% rings; dark control computed foreground/background match tokens. No production chart defect found.

Task I3-lock: complete (worker lock transaction fix; commits 4ee3574..acda20e, tests: real pg_stat_activity regression idle in transaction → idle; full uv run pytest → 708 passed, ruff check → pass, pyright → 0 errors).
Task I3: Ruling: commit the lifetime worker advisory-lock connection immediately after acquisition and explicit release — PostgreSQL session locks survive COMMIT, and holding an idle transaction for the lifetime of the worker prevents vacuum progress — cost if wrong: singleton ownership must remain protected; existing competing-worker and release tests pass.
Task I3: Ruling: retry each complete quarterly insider-load transaction on PostgreSQL DeadlockDetected (40P01) or SerializationFailure (40001), with a fresh session and exponential backoff plus jitter, at most three retries — failed transactions must roll back all staged and normalized rows; downloads/archives stay outside retries and completion checkpoints are saved only after successful COMMIT — cost if wrong: a quarter may take longer; exhausted concurrency errors and all other database errors remain visible job failures.
Task I3: Ruling: acquire bulk ticker_evidence locks in sorted canonical (issuer_cik, symbol) order, and acquire owners by CIK before ticker evidence in both live and bulk normalization — unordered accession sets and inverted owner/ticker phases permit deadlocks while these jobs run concurrently — cost if wrong: sorting adds work; newest-owner history and source display order are preserved.
Task I3: validation: observed RED for actual PostgreSQL concurrent owner/ticker deadlock, unsorted ticker upserts, and missing 40P01/40001 retries. GREEN: sorted SQL-observed keys; independent-session concurrent writes; successful full rollback/replay after two aborts with one archive download; four-attempt exhaustion and nonretryable failure propagation. Full backend suite 708 passed in 48.95s; ruff check passed; pyright 0 errors.
Task I7: Ruling: keep .serena/ tool working files out of Git through this checkout's .git/info/exclude — explicitly requested by the user; no project source or raw data changed — cost if wrong: other checkouts need their own local exclusion.

Task I3-deadlock: complete (commits acda20e..a7125b0, tests: concurrency/retry/order regressions RED → GREEN; full pytest → 708 passed; ruff/pyright → exit 0; docker compose up -d --build --no-deps worker → exit 0; signals jobs request backfill_all → existing request 3 requested → running).
Task I3: live recovery evidence at 2026-09-30 20:39 ET: request 3 running with done_steps=[backfill_reference] and datasets_done=[2016q1_form345.zip,2016q2_form345.zip]. Worker log starts backfill_insiders, skipping reference. Error cleared on re-request; no completed checkpoint or raw archive removed. The ten-year backfill remains incomplete.
Task I5: qualifying one-hour latency check is deferred to the next SEC business morning, 2026-10-01, because the rebuilt worker started at 20:38 ET after the specified 09:00–20:00 window. No latency success claimed.
Task I5: scheduled one-time thread follow-up "Signals live latency validation" for 09:15 on 2026-10-01 (automation signals-live-latency-validation). Check actual continuous worker uptime and the qualifying ET window before measuring; do not suppress catch-up filings or claim success from current high latency.

Task Catchup-1: Ruling: lift the seven-day reconcile cap only for catch-up and resume from app_state.reconcile_last_day, checkpointing each successful SEC business day and stopping at the first failed day — outages of 9 and 90 days must leave no unattempted dates or advance past failures — cost if wrong: long recoveries take longer; repeated completed filings are idempotent. With no previous checkpoint, catch-up checks 90 calendar days bounded by BACKFILL_START; the full historical job remains responsible for older history.
Task Catchup-1: Ruling: serialize cron maintenance, catch-up and historical backfills through a reentrant execution guard under the existing worker singleton lock, with a separate per-kind guard and durable running rows — scheduled/requested/catch-up paths must not overlap, while live_poll remains independent — cost if wrong: maintenance waits until the next catch-up check; requested jobs are requeued rather than falsely completed.
Task Catchup-1: Ruling: defer catch-up while historical backfills or scheduled maintenance are queued/running, retaining behind jobs visibly — prevents analytics from overtaking queued price repairs and avoids redundant historical imports during the initial full backfill — cost if wrong: freshness warnings remain until upstream work completes.
Task Catchup-1: Ruling: recompute analytics exactly once and last whenever catch-up repairs inputs, even if today's analytics cron was already satisfied — new filings/prices/reference data invalidate previously fresh calculations — cost if wrong: one extra full analytics run per repair batch.
Task Catchup-1: Ruling: compute last_due with CronTrigger in ET and compare fire instants in UTC, coalescing all cron misfires without a grace deadline — weekends and both DST folds must match the configured schedules across sleeps/restarts — cost if wrong: a missed schedule triggers an extra idempotent run.
Task Catchup-1: Ruling: record ingest_runs at start and update on finish, preserving requested-job completion/error precedence in health — running jobs were previously invisible until completion — cost if wrong: crashed run rows must be finalized by existing exclusive startup recovery.
Task Catchup-1: price evidence: real-DB prices_daily test seeds a last stored bar then supplies every missed NYSE trading day over a multi-day outage; loader fetches from the last stored date (one-bar overlap for adjustment repair) through current end and stores all missing dates. No price-loading implementation change needed.
Task Catchup-1: validation: calendar/weekend/DST/never-run/running/queued tests and missing module RED; visible-running-row, 9/90-day truncation and misfire setting RED; analytics after fresh input, failed-day checkpoint and queued-price precedence RED → GREEN. Full backend pytest 733 passed in 53.70s; Ruff pass; Pyright 0 errors. Frontend npm test 112 passed, npm run build and npm run lint exit 0 (existing nonfatal bundle/compiler warnings).
Task Catchup-1: complete (commits 1e20eff..f5d2e89, tests: backend pytest → 733 passed; Ruff/Pyright → exit 0; frontend npm test → 112 passed; build/lint → exit 0).
Task Catchup-2: Ruling: expose a structured catch_up health snapshot and recalculate behind jobs from durable records on every health request; warn before first scheduled successes and show interrupted recovery as error — cached state must not hide new failures or leave a restarted worker permanently appearing to be catching up — cost if wrong: initial empty installations show a warning until maintenance succeeds.
Task Catchup-2: Ruling: derive the header's elapsed age from successful run completion and the health query's response timestamp, sharing its 30-second cache with Data health — avoids inventing update times and keeps React rendering pure — cost if wrong: displayed minute boundaries can lag the next snapshot by up to 30 seconds.
Task Catchup-2: validation: /api/health missing catch_up field, interrupted-run state and Health page missing summary RED → GREEN; header absent component RED → 6 GREEN state tests. API contract/types regenerated. Full backend 737 passed in 54.30s; Ruff pass; Pyright 0 errors.
Task Catchup-2: frontend verification: npm test → 119 passed; npm run build → exit 0; npm run lint → exit 0 with only the existing TanStack Compiler warning.
Task Catchup-2: complete (commits f5d2e89..0000a68, tests: backend pytest → 737 passed; Ruff/Pyright → exit 0; frontend npm test → 119 passed; build/lint → exit 0).
Task Catchup-3: Ruling: preserve the earlier reconcile checkpoint when the normal capped job skips an older known gap, and treat an incomplete checkpoint as missed even after a recent successful short run — on wake the normal cron can run before catch-up, otherwise falsely covering only the latest week loses older filings — cost if wrong: catch-up rechecks some recently reconciled days; accession writes are idempotent. The 90-day cron-first regression failed on missing discovery and on missing business dates before the fix.
Task Catchup-3: Ruling: move a requested job deferred by an active execution to the queue's end without discarding params/progress — retaining its old queue priority could monopolize the short-job polling slot during a long backfill — cost if wrong: the busy job waits behind currently queued short work. Regression failed on retained requested_at before the fix.
Task Catchup-3: validation: cron-first 90-day gap and busy-request queue fairness RED → GREEN; full backend 739 passed in 53.48s, Ruff pass, Pyright 0 errors; frontend 119 passed, build/lint exit 0; mock Chromium smoke 12/12 including phone overflow and header route loading.

Task Catchup-3: complete (commits 0000a68..0ae801c, tests: cron-first 90-day gap and queue fairness RED → GREEN; full backend pytest → 739 passed; Ruff/Pyright → exit 0; frontend npm test → 119 passed; build/lint → exit 0; mock Chromium → 12/12).
Task Catchup-4: deployment: docker compose up -d --build worker api web → exit 0; migration exit 0, database healthy. Worker startup catch_up at 2026-09-30 21:08:06 ET persisted one successful run with ran=[], eight behind cron jobs, and deferred="Historical backfill is active". API health status=warn and no SEC pause; real Chromium health/header display the same state. Request 3 resumed with backfill_reference done and nine completed insider quarters preserved. No live database outage was simulated, and no claim of completed historical coverage or scheduled repairs is made.
Task Catchup-4: Ruling: document deferred startup recovery as successful detection with pending repairs, retaining the freshness warning — an active full historical backfill owns maintenance and its checkpoints must survive the rebuild — cost if wrong: users must wait for that backfill before scheduled repairs execute; automatic 15-minute checks continue.
Task Catchup-4: final verification: full backend pytest → 739 passed in 54.98s; Ruff → pass; Pyright → 0 errors; regenerated OpenAPI → no drift. Frontend npm test → 119 passed; npm run build and npm run lint → exit 0 (existing compiler/bundle warnings only). README, CLAUDE, HANDOFF and integration RESULTS updated; live ledger and tracked copy synchronized. .serena/, .env and data/ remain ignored.
Task Catchup-4: complete (commits 1e20eff..0ae801c, tests: all required backend/frontend checks → exit 0; mock Chromium → 12/12; rebuilt startup catch-up and real health/header → verified with historical-backfill deferral).
