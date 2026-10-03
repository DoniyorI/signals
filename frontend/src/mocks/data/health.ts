/**
 * `/api/health`: a default all-clear snapshot. F11 overrides this per test (via `server.use`)
 * to exercise the ok/warn/error banner variants, so this default only needs to be plausible.
 */
import type { Schema } from "@/api/client";

type HealthOut = Schema<"HealthOut">;

export function health(): HealthOut {
  return {
    status: "ok",
    completeness: { checked_at: "2024-06-07T21:12:47Z", gaps: 0, unavailable: 0 },
    catch_up: { status: "done", started_at: null, finished_at: null, ran: [], behind: [],
      error: null, deferred: null, last_updated_at: "2024-06-07T20:05:12Z" },
    sec_blocked_until: null,
    last_filing_seen_at: "2024-06-07T20:05:12Z",
    feed_delay_p50_s: 42,
    feed_delay_p95_s: 210,
    jobs: [
      { kind: "poll_feed", last_status: "ok", last_started_at: "2024-06-07T20:00:00Z", last_finished_at: "2024-06-07T20:00:12Z", last_error: null },
      { kind: "nightly_reconcile", last_status: "ok", last_started_at: "2024-06-07T06:00:00Z", last_finished_at: "2024-06-07T06:04:31Z", last_error: null },
      { kind: "load_prices", last_status: "ok", last_started_at: "2024-06-07T21:10:00Z", last_finished_at: "2024-06-07T21:12:47Z", last_error: null },
      { kind: "run_analytics", last_status: "ok", last_started_at: "2024-06-07T21:15:00Z", last_finished_at: "2024-06-07T21:18:03Z", last_error: null },
    ],
    parse_errors: [],
    backfill: [
      { step: "submissions", status: "done", done_units: 1, total_units: 1, updated_at: "2024-01-05T09:00:00Z" },
      { step: "insider_forms", status: "done", done_units: 2016, total_units: 2016, updated_at: "2024-06-07T05:00:00Z" },
      { step: "fund_13f", status: "done", done_units: 33, total_units: 33, updated_at: "2024-06-07T05:30:00Z" },
      { step: "prices", status: "done", done_units: 4, total_units: 4, updated_at: "2024-06-07T21:12:47Z" },
    ],
    coverage: {
      decisions_with_prices_pct: 0.97,
      decisions_last_price_exit_pct: 0.94,
      cusip_value_mapped_pct: 0.92,
      issuers_with_sector_pct: 0.75,
    },
  };
}
