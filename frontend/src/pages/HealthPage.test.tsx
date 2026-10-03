import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, expect, it, vi } from "vitest";
import type { Schema } from "@/api/client";
import { health } from "@/mocks/data/health";
import { completeness } from "@/mocks/data/completeness";
import { server } from "@/mocks/node";
import HealthPage from "./HealthPage";

const accession = "0001234567-24-000123";
const parseError: Schema<"ParseErrorOut"> = {
  accession_no: accession,
  error: "Missing ownershipDocument",
  filed_date: "2024-06-07",
  form_type: "4",
  sec_url: "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000123/filing.txt",
};
const queued: Schema<"JobRequestOut"> = {
  id: 42, kind: "reparse", status: "queued", requested_at: "2024-06-07T20:00:00Z",
  finished_at: null, error: null,
};

function snapshot(overrides: Partial<Schema<"HealthOut">> = {}) {
  server.use(http.get("/api/health", () => HttpResponse.json({ ...health(), ...overrides })));
}

function renderHealth() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><HealthPage /></QueryClientProvider>);
}

afterEach(() => vi.useRealTimers());

it.each([
  ["ok", "All systems normal"], ["warn", "Needs attention"], ["error", "Problem detected"],
] as const)("status banner text per status: %s", async (status, message) => {
  snapshot({ status });
  renderHealth();
  expect(await screen.findByText(message)).toBeInTheDocument();
});

it("shows SEC paused requests until a time in Eastern Time", async () => {
  snapshot({ status: "error", sec_blocked_until: "2024-06-07T20:10:00Z" });
  renderHealth();
  expect(await screen.findByText("SEC paused requests until Jun 7, 2024 4:10 PM ET")).toBeInTheDocument();
});

it("shows job failures, feed delays, relative last filing and every coverage metric", async () => {
  snapshot({
    last_filing_seen_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    jobs: [{ kind: "live_poll", last_status: "error", last_error: "SEC returned 403",
      last_started_at: "2024-06-07T20:00:00Z", last_finished_at: "2024-06-07T20:01:12Z" }],
  });
  renderHealth();
  expect(await screen.findByText("SEC returned 403")).toBeInTheDocument();
  expect(screen.getByText("live_poll")).toBeInTheDocument();
  expect(screen.getByText("Jun 7, 2024 4:00 PM ET")).toBeInTheDocument();
  expect(screen.getByText("42 s")).toBeInTheDocument();
  expect(screen.getByText("210 s")).toBeInTheDocument();
  expect(screen.getByText("5m ago")).toBeInTheDocument();
  for (const [label, value] of [
    ["Decisions with prices", "97.0%"], ["Decisions using last-price exit", "94.0%"],
    ["CUSIP value mapped", "92.0%"], ["Issuers with sector", "75.0%"],
  ]) {
    const metric = screen.getByText(label).parentElement!;
    expect(within(metric).getByText(value)).toBeInTheDocument();
  }
});

it("reparse posts accession and keeps the unresolved error and filing source visible", async () => {
  const user = userEvent.setup();
  snapshot({ parse_errors: [parseError] });
  let body: unknown;
  server.use(http.post("/api/jobs", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(queued, { status: 202 });
  }));
  renderHealth();
  await user.click(await screen.findByRole("button", { name: "Reparse" }));
  await screen.findByText("Reparse queued (job 42)");
  expect(body).toEqual({ kind: "reparse", params: { accessions: [accession] } });
  expect(screen.getByText("Missing ownershipDocument")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: accession })).toHaveAttribute("href", parseError.sec_url);
  expect(screen.getByRole("link", { name: accession })).toHaveAttribute("rel", "noreferrer");
  // Acceptance queues work; a subsequent worker failure must not permanently prevent retry.
  expect(screen.getByRole("button", { name: "Reparse" })).toBeEnabled();
});

it("disables reparse while posting and lets a failed request be retried", async () => {
  snapshot({ parse_errors: [parseError] });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  server.use(http.post("/api/jobs", async () => {
    await gate;
    return HttpResponse.json({ detail: "Worker queue unavailable" }, { status: 503 });
  }));
  const user = userEvent.setup();
  renderHealth();
  await user.click(await screen.findByRole("button", { name: "Reparse" }));
  expect(screen.getByRole("button", { name: "Queuing…" })).toBeDisabled();
  release();
  expect(await screen.findByText(/Could not queue reparse.*503/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reparse" })).toBeEnabled();
  server.use(http.post("/api/jobs", () => HttpResponse.json(queued, { status: 202 })));
  await user.click(screen.getByRole("button", { name: "Reparse" }));
  expect(await screen.findByText("Reparse queued (job 42)")).toBeInTheDocument();
});

it("start backfill requires confirmation and cancel queues nothing", async () => {
  const user = userEvent.setup();
  let body: unknown;
  server.use(http.post("/api/jobs", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ ...queued, kind: "backfill_all" }, { status: 202 });
  }));
  renderHealth();
  await user.click(await screen.findByRole("button", { name: "Start full backfill" }));
  const dialog = screen.getByRole("dialog", { name: "Start full backfill?" });
  expect(body).toBeUndefined();
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(body).toBeUndefined();
  await user.click(screen.getByRole("button", { name: "Start full backfill" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm backfill" }));
  await screen.findByText("Full backfill queued (job 42)");
  expect(body).toEqual({ kind: "backfill_all" });
});

it("shows backfill request progress and an actionable failure", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  server.use(http.post("/api/jobs", async () => {
    await gate;
    return HttpResponse.json({ detail: "Queue unavailable" }, { status: 503 });
  }));
  const user = userEvent.setup();
  renderHealth();
  await user.click(await screen.findByRole("button", { name: "Start full backfill" }));
  await user.click(screen.getByRole("button", { name: "Confirm backfill" }));
  expect(screen.getByRole("button", { name: "Queuing…" })).toBeDisabled();
  release();
  expect(await screen.findByText(/Could not queue full backfill.*503/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm backfill" })).toBeEnabled();
});

it("renders resumable progress without fabricating a percentage for an unknown total", async () => {
  snapshot({ backfill: [
    { step: "gap_fill", status: "running", done_units: 25, total_units: 100, updated_at: "2024-06-07T20:05:00Z" },
    { step: "prices", status: "pending", done_units: 12, total_units: null, updated_at: null },
    { step: "analytics", status: "pending", done_units: 0, total_units: 0, updated_at: null },
  ] });
  renderHealth();
  const bar = await screen.findByRole("progressbar", { name: "gap_fill" });
  expect(bar).toHaveAttribute("aria-valuenow", "25");
  expect(screen.getByText("25 / 100 units · 25.0%")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "prices" })).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByText("12 units · Total not known yet")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "analytics" })).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByText(/continues from saved checkpoints/)).toBeInTheDocument();
});

it("renders empty and unavailable health values explicitly", async () => {
  snapshot({ jobs: [], parse_errors: [], backfill: [], feed_delay_p50_s: null,
    feed_delay_p95_s: null, last_filing_seen_at: null,
    coverage: { cusip_value_mapped_pct: null, decisions_last_price_exit_pct: null,
      decisions_with_prices_pct: null, issuers_with_sector_pct: null } });
  renderHealth();
  expect(await screen.findByText("No job runs yet")).toBeInTheDocument();
  expect(screen.getByText("No unresolved parse errors")).toBeInTheDocument();
  expect(screen.getByText("No backfill checkpoints yet")).toBeInTheDocument();
  expect(screen.getByText("No filing seen yet")).toBeInTheDocument();
  expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
});

it("refreshes health after 30 seconds", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  renderHealth();
  await screen.findByText("All systems normal");
  snapshot({ status: "warn" });
  await act(async () => { await vi.advanceTimersByTimeAsync(29_999); });
  expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  vi.useRealTimers();
  expect(await screen.findByText("Needs attention")).toBeInTheDocument();
});

it("shows a health loading failure and supports retry", async () => {
  server.use(http.get("/api/health", () => HttpResponse.json({ detail: "Unavailable" }, { status: 503 })));
  renderHealth();
  await screen.findByText("Could not load data health");
  snapshot();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("All systems normal")).toBeInTheDocument();
});

it("keeps the last snapshot visible when a refresh fails and marks it stale", async () => {
  renderHealth();
  await screen.findByText("All systems normal");
  server.use(http.get("/api/health", () => HttpResponse.json({ detail: "Unavailable" }, { status: 503 })));
  fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));
  await waitFor(() => expect(screen.getByText(/Refresh failed.*last successful snapshot/)).toBeInTheDocument());
  expect(screen.getByText("All systems normal")).toBeInTheDocument();
});

it("shows catch-up timing, completed work and behind jobs", async () => {
  snapshot({catch_up: { status: "done", started_at: "2024-06-07T20:00:00Z", finished_at: "2024-06-07T20:05:00Z",
    ran: ["reconcile_daily", "prices_daily"], behind: ["analytics_full"], error: null, deferred: null, last_updated_at: null }});
  renderHealth();
  expect(await screen.findByRole("heading", {name:"Catch-up"})).toBeInTheDocument();
  expect(screen.getByText("Ran: reconcile_daily, prices_daily")).toBeInTheDocument();
  expect(screen.getByText("Behind: analytics_full")).toBeInTheDocument();
  expect(screen.getByText("Jun 7, 2024 4:05 PM ET")).toBeInTheDocument();
});

it("shows price, both return bases and tracked fund quarter coverage", async () => {
  const report = completeness();
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report,
    prices: { ...report.prices, covered: 37, pct: 0.37, loading: true },
    returns: { filed: { eligible: 20, covered: 10, pct: 0.5 }, executed: { eligible: 20, covered: 15, pct: 0.75 } },
    funds: { ...report.funds, total: 4, covered: 1, pct: 0.25 },
  })));
  renderHealth();
  const section = await screen.findByRole("region", { name: "Completeness" });
  for (const [label, value] of [
    ["Price history", "37.0%"], ["Returns from filing (6m)", "50.0%"],
    ["Returns from trade (6m)", "75.0%"], ["Tracked fund quarters", "25.0%"],
  ]) {
    expect(within(within(section).getByText(label).parentElement!).getByText(value)).toBeInTheDocument();
  }
  expect(within(section).getByText("Price loading is active")).toBeInTheDocument();
  expect(within(section).getByText("37 / 100 symbols through Jun 7, 2024")).toBeInTheDocument();
  expect(within(section).getByText("1 / 4 quarters across 2 tracked funds")).toBeInTheDocument();
});

it("reports filing completeness separately for every form family and preserves unknown counts", async () => {
  const report = completeness();
  const quarter = report.quarters[0];
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report, quarters: [
    { ...quarter, quarter: 1, family: "ownership", stored: 99, pct: 0.99, status: "gap" },
    { ...quarter, quarter: 1, family: "form144", indexed: null, stored: 1, pct: null, status: "unknown", indexed_through: null },
    { ...quarter, family: "stakes", stored: 80, pct: 0.8, status: "in_progress" },
    { ...quarter, quarter: 1, family: "13f", status: "complete" },
  ] })));
  renderHealth();
  await userEvent.setup().click(await screen.findByText("Filing completeness by quarter (4 rows)"));
  const table = await screen.findByRole("table", { name: "Filing completeness by quarter" });
  const ownership = within(table).getByRole("row", { name: /2024 Q1 Ownership/ });
  expect(within(ownership).getByText("99.0%")).toBeInTheDocument();
  expect(within(ownership).getByText("Gap")).toBeInTheDocument();
  const form144 = within(table).getByRole("row", { name: /2024 Q1 Form 144/ });
  expect(within(form144).getByText("Not checked")).toBeInTheDocument();
  expect(within(form144).getAllByText("Unknown")).toHaveLength(3);
  expect(within(table).getByRole("row", { name: /2024 Q2 Stakes.*In progress/ })).toBeInTheDocument();
  expect(within(table).getByRole("row", { name: /2024 Q1 13F.*Complete/ })).toBeInTheDocument();
});

it("shows each tracked fund quarter and yearly insider transaction counts", async () => {
  const report = completeness();
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report,
    funds: { ...report.funds, covered: 1, pct: 0.5, quarters: [
      { ...report.funds.quarters[0], present: true }, { ...report.funds.quarters[1], present: false },
    ] }, insider_transactions: [{ year: 2023, count: 123 }, { year: 2024, count: 25 }],
  })));
  renderHealth();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Tracked fund quarter details (2 rows)"));
  const funds = await screen.findByRole("table", { name: "Tracked fund quarter coverage" });
  expect(within(funds).getByRole("row", { name: /3000001.*Present/ })).toBeInTheDocument();
  expect(within(funds).getByRole("row", { name: /3000002.*Missing/ })).toBeInTheDocument();
  await user.click(screen.getByText("Insider transactions by year"));
  const transactions = await screen.findByRole("table", { name: "Insider transactions by year" });
  expect(within(transactions).getByRole("row", { name: "2023 123" })).toBeInTheDocument();
});

it("shows unavailable accessions and the reason retries stopped after three attempts", async () => {
  const report = completeness();
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report, unavailable: [{
    accession_no: accession, cik: 1234567, family: "ownership", year: 2024, quarter: 2,
    attempts: 3, error: "SEC returned 404", updated_at: "2024-06-07T20:00:00Z",
  }] })));
  renderHealth();
  expect(await screen.findByText("Retries stopped after 3 attempts")).toBeInTheDocument();
  expect(screen.getByText("SEC returned 404")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: accession })).toHaveAttribute("href",
    "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000123/");
});

it("says when completeness has never been checked and does not invent null percentages", async () => {
  const report = completeness();
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report, checked_at: null,
    prices: { ...report.prices, total: 0, covered: 0, pct: null },
    returns: { filed: { eligible: 0, covered: 0, pct: null }, executed: { eligible: 0, covered: 0, pct: null } },
    funds: { tracked: 0, total: 0, covered: 0, pct: null, quarters: [] },
  })));
  renderHealth();
  expect(await screen.findByText("Completeness has not been checked yet.")).toBeInTheDocument();
  const section = screen.getByRole("region", { name: "Completeness" });
  expect(within(section).getAllByText("Unknown")).toHaveLength(4);
  expect(within(section).queryByText("0.0%")).not.toBeInTheDocument();
});

it("shows completeness failures while leaving operational health visible", async () => {
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ detail: "Unavailable" }, { status: 503 })));
  renderHealth();
  expect(await screen.findByText("Completeness report didn't load")).toBeInTheDocument();
  expect(screen.getByText("All systems normal")).toBeInTheDocument();
});

it("refreshes completeness alongside operational health", async () => {
  renderHealth();
  const section = await screen.findByRole("region", { name: "Completeness" });
  await within(section).findByText("No price load is active");
  const report = completeness();
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report,
    prices: { ...report.prices, covered: 37, pct: 0.37, loading: true },
  })));
  fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));
  expect(await within(section).findByText("37.0%")).toBeInTheDocument();
});

it("mounts fund coverage rows only while the disclosure is open", async () => {
  renderHealth();
  const summary = await screen.findByText("Tracked fund quarter details (2 rows)");
  const section = screen.getByRole("region", { name: "Completeness" });
  expect(within(section).queryByRole("table", { name: "Tracked fund quarter coverage", hidden: true })).not.toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(summary);
  expect(await screen.findByRole("table", { name: "Tracked fund quarter coverage" })).toBeInTheDocument();
  await user.click(summary);
  await waitFor(() => expect(within(section).queryByRole("table", { name: "Tracked fund quarter coverage", hidden: true })).not.toBeInTheDocument());
});

it("defaults the fund matrix to the latest quarter and allows choosing an earlier one", async () => {
  const report = completeness();
  server.use(http.get("/api/health/completeness", () => HttpResponse.json({ ...report,
    funds: { ...report.funds, total: 3, covered: 2, pct: 2 / 3, quarters: [
      { cik: 3000001, year: 2024, quarter: 1, period: "2024-03-31", present: true },
      { cik: 3000001, year: 2024, quarter: 2, period: "2024-06-30", present: false },
      { cik: 3000002, year: 2024, quarter: 2, period: "2024-06-30", present: true },
    ] },
  })));
  renderHealth();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Tracked fund quarter details (3 rows)"));
  const filter = await screen.findByRole("combobox", { name: "Fund quarter" });
  expect(filter).toHaveValue("2024-06-30");
  const table = screen.getByRole("table", { name: "Tracked fund quarter coverage" });
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(within(table).getByRole("row", { name: /3000001.*2024 Q2.*Missing/ })).toBeInTheDocument();
  await user.selectOptions(filter, "2024-03-31");
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getByRole("row", { name: /3000001.*2024 Q1.*Present/ })).toBeInTheDocument();
});
