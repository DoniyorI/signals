import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppWithRouter } from "@/App";
import type { Schema } from "@/api/client";
import { HttpResponse, http } from "msw";
import { server } from "@/mocks/node";
import { insiderDecisions, insiderHeader, insiderPerformance } from "@/mocks/data/insiders";
import { coverageFixture } from "@/test/coverage";

// lightweight-charts draws on canvas, which jsdom doesn't implement (components.test.tsx uses
// the same stub for the same reason).
vi.mock("lightweight-charts", () => {
  const series = { setData: vi.fn(), applyOptions: vi.fn() };
  const chart = {
    addSeries: vi.fn(() => series),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  };
  return {
    createChart: vi.fn(() => chart),
    createSeriesMarkers: vi.fn(),
    CandlestickSeries: {},
    LineSeries: {},
    AreaSeries: {},
    ColorType: { Solid: "solid" },
  };
});

let requestPaths: { method: string; url: string }[] = [];

function onRequestStart({ request }: { request: Request }) {
  requestPaths.push({ method: request.method, url: request.url });
}

beforeEach(() => {
  requestPaths = [];
  server.events.on("request:start", onRequestStart);
});

afterEach(() => {
  server.events.removeListener("request:start", onRequestStart);
});

it("renders header metrics", async () => {
  render(<AppWithRouter initialPath="/insider/2000001" />);
  expect(await screen.findByRole("heading", { name: "Doe Jane" })).toBeInTheDocument();
  expect(await screen.findByText("78 · High")).toBeInTheDocument();
  expect(await within(screen.getByRole("region", { name: "Performance" })).findByRole("table")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(0);
});

it("renders not-enough-data state", async () => {
  render(<AppWithRouter initialPath="/insider/2000005" />);
  await screen.findByRole("heading", { name: "New Person" });
  expect(await within(screen.getByRole("region", { name: "Performance" })).findByText("Not enough data yet")).toBeInTheDocument();
  const roiStat = screen.getByText("Avg ROI (6m vs SPY)").closest("div");
  expect(roiStat).not.toBeNull();
  expect(within(roiStat as HTMLElement).getByText("—")).toBeInTheDocument();
});

it("basis toggle refetches with basis=executed", async () => {
  render(<AppWithRouter initialPath="/insider/2000001" />);
  await screen.findByRole("heading", { name: "Doe Jane" });
  // The basis ToggleGroup is a single-select radiogroup (Radix), not plain buttons.
  await userEvent.setup().click(screen.getByText("From trade"));
  await waitFor(() =>
    expect(
      requestPaths.some(
        (r) => r.url.includes("/api/insiders/2000001") && !r.url.includes("decisions") && r.url.includes("basis=executed"),
      ),
    ).toBe(true),
  );
});

it("tabs switch via url", async () => {
  render(<AppWithRouter initialPath="/insider/2000001?tab=holdings" />);
  await screen.findByRole("heading", { name: "Doe Jane" });
  expect(await screen.findByText("By sector")).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "Transactions" }));
  expect(await screen.findByText("Show superseded")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Form 144" }));
  expect(await screen.findByText("No Form 144 notices")).toBeInTheDocument();
});

it("watch button creates default watchlist then adds item", async () => {
  render(<AppWithRouter initialPath="/insider/2000001" />);
  await screen.findByRole("heading", { name: "Doe Jane" });
  await userEvent.setup().click(screen.getByRole("button", { name: "Watch" }));
  await waitFor(() =>
    expect(requestPaths.filter((r) => r.method === "POST").map((r) => new URL(r.url).pathname)).toEqual([
      "/api/watchlists",
      "/api/watchlists/1/items",
    ]),
  );
});

it("explains one completed trade using actual returns rather than the total decisions", async () => {
  const decisions = insiderDecisions(2000005, "filed", false, null);
  const completed = { ...decisions[0], returns: decisions[0].returns.map((r) => r.horizon === "6m" ? { ...r, complete: true, raw: 0.1, excess_spy: 0.02 } : r) };
  server.use(http.get("/api/insiders/:cik/decisions", () => HttpResponse.json({ items: [completed], next_cursor: null })));
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await screen.findByText("Needs 3+ completed trades (has 1).")).toBeInTheDocument();
});

it("shows an insider performance API error instead of treating it as no data", async () => {
  server.use(http.get("/api/insiders/:cik/performance", () => HttpResponse.json({ detail: "unavailable" }, { status: 500 })));
  render(<AppWithRouter initialPath="/insider/2000001" />);
  expect(await screen.findByText("Performance didn't load", {}, { timeout: 3000 })).toBeInTheDocument();
});

it("shares the coverage query across missing ratings and performance", async () => {
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37, missingSymbols: ["XYZ"] }))),
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => HttpResponse.json(refreshJob("running", { stage: "prices", symbols_done: 1, symbols_total: 3 }))),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await screen.findByText("Prices 37% loaded. Rating appears after returns are calculated.")).toBeInTheDocument();
  expect(await screen.findByText("1 of 3 symbols checked.")).toBeInTheDocument();
  expect(requestPaths.filter((r) => new URL(r.url).pathname === "/api/health/completeness")).toHaveLength(1);
});

it("does not present a partial decision page as an exact completed trade count", async () => {
  const header = insiderHeader(2000005, "filed", false)!;
  const decisions = insiderDecisions(2000005, "filed", false, null);
  server.use(
    http.get("/api/insiders/:cik", () => HttpResponse.json({ ...header, n_decisions: 1500 })),
    http.get("/api/insiders/:cik/decisions", () => HttpResponse.json({ items: decisions, next_cursor: "more" })),
  );
  render(<AppWithRouter initialPath="/insider/2000005?tab=transactions" />);
  expect(await screen.findByText("No performance data yet")).toBeInTheDocument();
  expect(screen.queryByText(/Needs 3\+ completed trades \(has/)).not.toBeInTheDocument();
  const decisionRequests = requestPaths.filter((r) => new URL(r.url).pathname.endsWith("/decisions"));
  expect(decisionRequests).toHaveLength(2); // Initial page plus the scoped job's completion refresh.
  expect(decisionRequests.every((r) => !new URL(r.url).searchParams.has("cursor"))).toBe(true);
});

function refreshJob(status: string, progress: Record<string, unknown> = {}, error: string | null = null): Schema<"JobRequestOut"> {
  return {
    id: 42, kind: "refresh_insider_performance", status, requested_at: "2026-10-03T12:00:00Z",
    finished_at: status === "done" || status === "failed" ? "2026-10-03T12:01:00Z" : null,
    error, progress: { owner_cik: 2000005, ...progress },
  };
}

function jobRequests() {
  return requestPaths.filter((r) => r.method === "POST" && new URL(r.url).pathname === "/api/jobs");
}

it("requests only this insider's missing performance and shows scoped price progress", async () => {
  const bodies: unknown[] = [];
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0, missingSymbols: ["XYZ"] }))),
    http.post("/api/jobs", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json(refreshJob("requested"), { status: 202 });
    }),
    http.get("/api/jobs/:job_id", () => HttpResponse.json(refreshJob("running", { stage: "prices", symbols_done: 2, symbols_total: 3 }))),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  const region = await screen.findByRole("region", { name: "Performance" });
  expect(await within(region).findByText("2 of 3 symbols checked.")).toBeInTheDocument();
  expect(within(region).getByRole("progressbar", { name: "This profile's price checks" })).toHaveAttribute("aria-valuenow", "67");
  expect(within(region).queryByText(/0% done/)).not.toBeInTheDocument();
  expect(bodies).toEqual([{ kind: "refresh_insider_performance", params: { owner_cik: 2000005 } }]);
});

it("prepares an uncomputed profile even when the global completeness report is unavailable", async () => {
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json({ detail: "Coverage unavailable" }, { status: 503 })),
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => HttpResponse.json(refreshJob("running", { stage: "prices", symbols_done: 1, symbols_total: 3 }))),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await within(await screen.findByRole("region", { name: "Performance" })).findByText("1 of 3 symbols checked.")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
});

it("reports missing scoped prices without claiming those symbols loaded", async () => {
  server.use(
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => HttpResponse.json(refreshJob("running", {
      stage: "prices", symbols_done: 2, symbols_total: 3, missing: ["XYZ"],
    }))),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  const region = await screen.findByRole("region", { name: "Performance" });
  expect(await within(region).findByText("2 of 3 symbols checked.")).toBeInTheDocument();
  expect(within(region).getByText("1 symbol has no price data available.")).toBeInTheDocument();
  expect(within(region).queryByText(/symbols loaded/)).not.toBeInTheDocument();
});

it("polls the scoped job then refreshes the curve and profile stats when it completes", async () => {
  let polls = 0;
  let complete = false;
  const header = insiderHeader(2000005, "filed", false)!;
  server.use(
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => {
      polls += 1;
      complete = polls >= 3;
      return HttpResponse.json(refreshJob(complete ? "done" : polls === 1 ? "requested" : "running",
        { stage: complete ? "done" : "analytics", symbols_done: 3, symbols_total: 3 }));
    }),
    http.get("/api/insiders/:cik", () => HttpResponse.json(complete ? {
      ...header, updated_at: "2026-10-03T12:01:00Z", rating: { score: 78, confidence: "high", n: 10 }, avg_roi_6m: 0.12,
    } : header)),
    http.get("/api/insiders/:cik/performance", () => HttpResponse.json(insiderPerformance(complete ? 2000001 : 2000005, "filed", false))),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await screen.findByText("Performance refresh is queued")).toBeInTheDocument();
  expect(await screen.findByText("Calculating this profile’s performance", {}, { timeout: 4000 })).toBeInTheDocument();
  const region = screen.getByRole("region", { name: "Performance" });
  expect(await within(region).findByRole("table", {}, { timeout: 4000 })).toBeInTheDocument();
  expect(await screen.findByText("78 · High")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
  expect(polls).toBe(3);
  expect(requestPaths.filter((r) => new URL(r.url).pathname === "/api/insiders/2000005/performance")).toHaveLength(2);
});

it("shows a scoped worker failure without enqueueing again after changing basis", async () => {
  server.use(
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => HttpResponse.json(refreshJob("failed", { stage: "prices" }, "Provider rate limit exceeded"))),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await screen.findByText("Performance refresh needs attention")).toBeInTheDocument();
  expect(screen.getByText("Provider rate limit exceeded")).toBeInTheDocument();
  await userEvent.setup().click(screen.getByText("From trade"));
  await waitFor(() => expect(requestPaths.some((r) => r.url.includes("/performance?basis=executed"))).toBe(true));
  expect(await screen.findByText("Performance refresh needs attention")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
});

it("does not retry a rejected refresh request automatically", async () => {
  server.use(http.post("/api/jobs", () => HttpResponse.json({ detail: "Worker unavailable" }, { status: 503 })));
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await screen.findByText("Performance refresh couldn't start")).toBeInTheDocument();
  expect(screen.getByText(/Worker unavailable/)).toBeInTheDocument();
  await userEvent.setup().click(screen.getByText("From trade"));
  await waitFor(() => expect(requestPaths.some((r) => r.url.includes("/performance?basis=executed"))).toBe(true));
  expect(await screen.findByText("Performance refresh couldn't start")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
});

it("shows a job-status API error without enqueueing a replacement job", async () => {
  server.use(
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => HttpResponse.json({ detail: "Job not found" }, { status: 404 })),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await screen.findByText("Performance refresh status didn't load", {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByText("Job not found")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
});

it("keeps insufficient results after completion without following the global price backfill or queueing again", async () => {
  const header = insiderHeader(2000005, "filed", false)!;
  let complete = false;
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0, missingSymbols: ["XYZ"] }))),
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => {
      complete = true;
      return HttpResponse.json(refreshJob("done", { stage: "done", symbols_done: 1, symbols_total: 1 }));
    }),
    http.get("/api/insiders/:cik", ({ request }) => HttpResponse.json({ ...header, basis: new URL(request.url).searchParams.get("basis") ?? "filed",
      updated_at: complete ? "2026-10-03T12:01:00Z" : null, rating: { score: null, confidence: null, n: 1 } })),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  const region = await screen.findByRole("region", { name: "Performance" });
  expect(await within(region).findByText("Needs 3+ completed trades (has 1).")).toBeInTheDocument();
  expect(within(region).getByText("Not enough data yet")).toBeInTheDocument();
  expect(within(region).queryByText(/0% done/)).not.toBeInTheDocument();
  await userEvent.setup().click(screen.getByText("From trade"));
  await waitFor(() => expect(requestPaths.some((r) => r.url.includes("/performance?basis=executed"))).toBe(true));
  expect(await within(await screen.findByRole("region", { name: "Performance" })).findByText("Needs 3+ completed trades (has 1).")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
});

it("does not queue a refresh for already-calculated insufficient stats", async () => {
  const header = insiderHeader(2000005, "filed", false)!;
  server.use(http.get("/api/insiders/:cik", () => HttpResponse.json({ ...header, updated_at: "2026-10-03T12:01:00Z" })));
  render(<AppWithRouter initialPath="/insider/2000005" />);
  expect(await within(await screen.findByRole("region", { name: "Performance" })).findByText("Needs 3+ completed trades (has 0).")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(0);
});

it("shows the completed profile's insufficient result even when global completeness fails", async () => {
  const header = insiderHeader(2000005, "filed", false)!;
  let complete = false;
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json({ detail: "Coverage unavailable" }, { status: 503 })),
    http.post("/api/jobs", () => HttpResponse.json(refreshJob("requested"), { status: 202 })),
    http.get("/api/jobs/:job_id", () => {
      complete = true;
      return HttpResponse.json(refreshJob("done", { stage: "done", symbols_done: 1, symbols_total: 1 }));
    }),
    http.get("/api/insiders/:cik", () => HttpResponse.json({ ...header, updated_at: complete ? "2026-10-03T12:01:00Z" : null,
      rating: { score: null, confidence: null, n: 1 } })),
  );
  render(<AppWithRouter initialPath="/insider/2000005" />);
  const region = await screen.findByRole("region", { name: "Performance" });
  expect(await within(region).findByText("Needs 3+ completed trades (has 1).")).toBeInTheDocument();
  expect(jobRequests()).toHaveLength(1);
});
