# Integration Implementation Plan (main agent)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the six workstreams and run the real 10-year backfill. Then prove each of the spec's success criteria (section 2) with evidence, and hand the working dashboard to the user.

**Architecture:** Branches merge into `feat/sec-dashboard`, then a thin cross-workstream test runs, then the full Docker stack starts against live SEC, Alpaca and OpenFIGI. The main agent verifies and reviews everything. No additional subagents are used, because the 6-subagent limit is already spent.

**Tech Stack:** Everything from the earlier plans, plus `curl` for timings and Playwright against the real stack.

**Spec:** `docs/superpowers/specs/2026-09-27-sec-dashboard-design.md`, section 2 (success criteria) and section 16 (risks).

## Global Constraints

- Everything in `00-overview.md` › Global Constraints.
- The network is allowed in this plan, but only through the application: the worker's `SecClient` and providers, and `scripts/spot_check.py`.
- **Never force-push.** Merge conflicts in foundation-owned files are resolved in favor of the foundation contract.

## Review Focus

Re-verify the five overview items against real data:
1. **Ticker changes:** `/company/META` shows FB history and `formerly FB`.
2. **Good Friday entries:** a Form 4 accepted on 2024-03-29 has `entry_date=2024-04-01` and `entry_kind=open`.
3. **Empty profiles:** the newest insider in the feed renders `Not enough data yet`.
4. **Splits:** NVDA (10:1 split, 2024-06-10) decisions before the split have sensible returns.
5. **Feed bursts:** the reconcile's `missed` count stays small, and the feed shows no duplicates.

---

### Task I1: Merge workstreams, cross-workstream test

**Files:**
- Create: `backend/tests/integration/test_cross_workstream.py`
- Modify: whatever the merges touch

- [ ] **Step 1: Merge.** Run `git merge --no-ff <branch>` for `ws/c-reference`, `ws/a-insider`, `ws/b-funds`, `ws/d-analytics`, `ws/e-api` and `ws/f-frontend`, in that order, resolving conflicts. If `uv run alembic heads` shows more than one head, run `uv run alembic merge heads -m merge_workstreams`.

- [ ] **Step 2: Write the cross-workstream test:**

```python
def test_filing_to_api_end_to_end(session, fixture_bytes, api_client_real_curves):
    import signals.ingest.handlers  # registers the A and B handlers
    for key in ["form4_buy_single", "form4_joint", "f13f_small"]:
        assert ingest_raw(session, fixture_bytes(key), source="test", raw_path=None, first_seen_at=None,
                          settings=test_settings(), archive=tmp_archive()).status == "parsed"
    seed_prices_for_all_symbols(session)          # fake provider -> load_prices over build_price_universe
    run_full(lambda: session, as_of=date(2025, 12, 31))
    owner = manifest["form4_buy_single"]["expect"]["owner_ciks"][0]
    h = api_client_real_curves.get(f"/api/insiders/{owner}").json()
    assert h["n_decisions"] >= 1
    feed = api_client_real_curves.get("/api/feed", params={"include_10b5_1": "true"}).json()["items"]
    assert {i["accession_no"] for i in feed} >= {manifest[k]["accession"] for k in ["form4_buy_single", "form4_joint"]}
    perf = api_client_real_curves.get(f"/api/insiders/{owner}/performance").json()
    assert perf["points"][0]["nav"] == 1.0
```

- [ ] **Step 3:** Run `cd backend && uv run pytest -q && uv run ruff check && uv run pyright`, then `cd ../frontend && npm test && npm run build && npm run lint`. Expected: everything green. Fix anything that fails in the owning module.

- [ ] **Step 4:** Run `uv run signals openapi --out ../frontend/src/api/openapi.json && git diff --exit-code frontend/src/api/openapi.json`. Expected: no diff.

- [ ] **Step 5: Commit** with message `test: cross-workstream end-to-end test after merging workstreams`.

---

### Task I2: Bring up the stack

- [ ] **Step 1:** Run `docker compose up -d --build`, then `docker compose ps`. Expected: `db` is healthy, `migrate` exited 0, and `api`, `worker` and `web` are running.
- [ ] **Step 2:** Run `curl -s 127.0.0.1:8000/api/health | python3 -m json.tool`. Expected: `"status"` is `ok` or `warn`, and there's no `sec_blocked_until`.
- [ ] **Step 3:** Open `http://127.0.0.1:5173` in the browser pane. Expected: the feed page loads and is empty, which is correct before the backfill.

---

### Task I3: Real backfill

- [ ] **Step 1:** Run `docker compose exec worker signals jobs request backfill_all`. Expected: it prints the request id.
- [ ] **Step 2: Monitor.** Watch `/api/health` backfill progress and `docker compose logs -f worker`. This runs for hours, and the steps resume after a restart.

  If a step fails:
  1. Read the error in `job_requests.error`.
  2. Fix it in the owning module, with a failing test first.
  3. Run `docker compose up -d --build worker`.
  4. Re-request the job. It resumes from its progress.

- [ ] **Step 3: Checkpoints.** Run these SQL queries (`docker compose exec db psql -U signals -c …`) as each step completes:

| Step | Check | Expected |
|---|---|---|
| backfill_reference | `select count(*) from issuers where sic is not null` | > 8,000 |
| backfill_reference | `select count(*) from filing_acceptance` | > 1,000,000 |
| backfill_insiders | `select count(*) from filings where form_type in ('4','4/A') and filed_date >= '2016-01-01'` | > 1,500,000 |
| backfill_insiders | `select count(*) from filings where accepted_at is null and form_type in ('3','4','5')` | < 1% of the above |
| backfill_insiders | `select count(*) from form144_notices` | > 50,000 |
| backfill_funds | `select count(*) from fund_filings where period_of_report >= '2016-01-01'` | > 150,000 |
| backfill_funds | `select count(*) from ownership_stakes` | > 20,000 |
| backfill_funds | Data health `cusip_value_mapped_pct` | ≥ 0.90 |
| backfill_prices | `select count(distinct symbol) from prices_daily` | > 5,000 |
| analytics_full | `select finished_at - started_at from ingest_runs where job='analytics_full' order by id desc limit 1` | < 30 minutes |
| analytics_full | Data health `decisions_with_prices_pct` | ≥ 0.95 |

  If a number misses badly, investigate before moving on. Record the actual numbers in the final report.

- [ ] **Step 4: Survivorship check.** If `decisions_last_price_exit_pct` is above 0.05, or the share of decisions with no prices is above 5%, tell the user and propose the one-off delisted-price source (spec §16). Don't buy anything.

---

### Task I4: Spot-check script (success criterion 4)

**Files:**
- Create: `scripts/spot_check.py`
- Test: `backend/tests/unit/test_spot_check.py`

**Interfaces:**
- `pick_sample(session, n=20, seed=7) -> list[str]`: accessions of Form 4 filings with P or S rows, stratified across the years 2016–2026 (2 per year, the rest random).
- `compare(db_rows, parsed_doc) -> list[str]`: returns mismatch descriptions for code, transaction date, shares (±0.005), price (±0.005, because the bulk data keeps 2 decimals) and shares owned after (±0.5).
- The script fetches each sample's `.txt` fresh through `SecClient`, parses it with `parse_ownership`, compares it with the database rows, and prints `N/20 match`, any mismatches, and 5 filing URLs for the user to check by eye.

- [ ] **Step 1: Write the failing test.** `compare` of a hand-built row and document with a price of 12.3456 in XML against 12.35 in the database gives no mismatch. A shares difference of 1 gives exactly one mismatch.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_spot_check.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/unit/test_spot_check.py`. Expected: pass. Then run `docker compose exec worker python /app/scripts/spot_check.py`. Expected: `20/20 match`. Any mismatch is a bug to fix before continuing.
- [ ] **Step 5: Commit** with message `feat: spot-check script comparing stored rows with fresh SEC parses`.

---

### Task I5: Live latency (success criterion 3)

- [ ] **Step 1:** On an SEC business day between 09:00 and 20:00 ET, with the worker running for at least 1 hour, read `/api/health`. Expected: `feed_delay_p95_s <= 120`. If it's higher, inspect the `live_poll` ingest runs (fetch errors, pagination depth) and fix. If the check falls outside business hours, schedule it for the next business morning and say so in the report instead of claiming it passed.

---

### Task I6: End-to-end smoke test on real data (success criteria 1, 5, 6)

**Files:**
- Modify: `frontend/e2e/smoke.spec.ts`, so route ids come from env (`E2E_INSIDER`, `E2E_COMPANY`, `E2E_FUND`) and default to the mock ids.

- [ ] **Step 1:** Choose real ids: a frequent insider buyer from `/api/screener/insiders?min_decisions=10`, company `AAPL`, and fund `1067983` (Berkshire).
- [ ] **Step 2:** Run `cd frontend && E2E_BASE_URL=http://127.0.0.1:5173 E2E_INSIDER=<cik> E2E_COMPANY=AAPL E2E_FUND=1067983 npx playwright test`. Expected: every route passes with no console errors.
- [ ] **Step 3:** Check the profile coverage. `select count(distinct o.owner_cik) from decision_owners o left join profile_stats p on p.cik=o.owner_cik and p.kind='insider' where p.cik is null` should return `0`.
- [ ] **Step 4:** Check the fund coverage. `select count(*) from fund_managers where is_tracked and cik not in (select distinct cik from fund_nav_daily)` should return `0`.
- [ ] **Step 5:** Run `for i in $(seq 20); do curl -s -o /dev/null -w "%{time_total}\n" "127.0.0.1:8000/api/feed?limit=50"; done | sort -n | tail -2`. Expected: the p95 is under 0.3 s. Run the same loop on `/api/insiders/<cik>/performance` after one warm-up call. Expected: under 0.3 s.
- [ ] **Step 6: Commit** with message `test(web): env-driven e2e ids for real-data smoke runs`.

---

### Task I7: Final review, security sweep, docs, handoff

- [ ] **Step 1: Security sweep.**
  - Run `git log --all -p | grep -c -F -f <(sed -n -E 's/^(ALPACA_API_KEY|ALPACA_SECRET_KEY)=//p' .env; sed -n -E 's/^SEC_USER_AGENT=.* ([^ ]+@[^ "]+).*/\1/p' .env)`. This reads the secret values from `.env` at runtime; never type them into commands or files. Expected: `0`.
  - `git check-ignore .env data/` should print both paths.
  - `grep -rn "0.0.0.0" docker-compose.yml` should show only container-internal binds; every published port is prefixed `127.0.0.1:`.
- [ ] **Step 2: Whole-branch review by the main agent** against the spec. Check:
  - Every SEC request goes through `SecClient`.
  - No `except: pass` and no swallowed errors (`grep -rn "except" backend/src` and inspect each).
  - Follower returns never use the trade date alone.
  - Nothing is keyed by ticker.
  - Raw data is never deleted.

  Fix what you find, test-first, and commit each fix.
- [ ] **Step 3: Docs.**
  - Update `README.md` with how to run it, how the backfill works, and what each page shows.
  - Update `CLAUDE.md` with the final ownership map and commands.
  - Record the backfill numbers and spot-check results in `docs/superpowers/plans/2026-09-27-sec-dashboard/RESULTS.md`.

  Commit with message `docs: final README, CLAUDE.md and results`.
- [ ] **Step 4: Handoff.** Use superpowers:finishing-a-development-branch. Present the options (merge `feat/sec-dashboard` into `main` locally, or keep the branch) and wait for the user's choice. Report to the user:
  - The success criteria with their evidence (the numbers from I3–I6).
  - Anything deferred (for example I5 scheduled for the next business day).
  - The next sub-project in line (#2 Signals & alerts).
