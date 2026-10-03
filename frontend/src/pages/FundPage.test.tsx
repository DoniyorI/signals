import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AppWithRouter } from "@/App";
import { HttpResponse, http } from "msw";
import { server } from "@/mocks/node";
import { fundHoldings, fundPerformance } from "@/mocks/data/funds";
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

it("renders holdings and exits separately", async () => {
  render(<AppWithRouter initialPath="/fund/3000001" />);
  await screen.findByRole("heading", { name: "Example Capital Management" });
  expect(await screen.findByText("Exited this quarter")).toBeInTheDocument();
  expect(screen.getAllByText("ACME").length).toBeGreaterThan(0);
  expect(screen.getAllByText("XYZA").length).toBeGreaterThan(0);
});

it("untracked fund message", async () => {
  render(<AppWithRouter initialPath="/fund/3999999" />);
  await screen.findByRole("heading", { name: "Small Fry Advisors" });
  expect(await screen.findByText("Performance is available for tracked funds only")).toBeInTheDocument();
});

it("high conviction star shown", async () => {
  render(<AppWithRouter initialPath="/fund/3000001" />);
  await screen.findByRole("heading", { name: "Example Capital Management" });
  expect((await screen.findAllByText("★")).length).toBeGreaterThan(0);
});

it("explains a cash-only curve with unmapped CUSIPs during global price loading", async () => {
  const performance = fundPerformance(3000001, "filed")!;
  const holdings = fundHoldings(3000001, null)!;
  server.use(
    http.get("/api/funds/:cik/performance", () => HttpResponse.json({ ...performance, coverage_pct: 0,
      points: performance.points.slice(0, 2).map((point) => ({ ...point, nav: 1 })) })),
    http.get("/api/funds/:cik/holdings", () => HttpResponse.json({ ...holdings,
      rows: holdings.rows.map((row) => ({ ...row, security: { ...row.security, ticker: null, issuer_cik: null } })), next_cursor: null })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37 }))),
  );
  render(<AppWithRouter initialPath="/fund/3000001" />);
  expect(await screen.findByText("No price data for this security.")).toBeInTheDocument();
  expect(screen.queryByText("This portfolio")).not.toBeInTheDocument();
  expect(screen.queryByText(/Performance appears when prices finish loading/)).not.toBeInTheDocument();
});

it("explains a priced fund waiting for its price history", async () => {
  const performance = fundPerformance(3000001, "filed")!;
  server.use(
    http.get("/api/funds/:cik/performance", () => HttpResponse.json({ ...performance, points: [], coverage_pct: 0 })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37, missingSymbols: ["ACME", "GLBX"] }))),
  );
  render(<AppWithRouter initialPath="/fund/3000001" />);
  expect(await screen.findByText("Performance appears when prices finish loading (37% done).")).toBeInTheDocument();
});

it("does not diagnose every fund security from a partial unmapped holdings page", async () => {
  const performance = fundPerformance(3000001, "filed")!;
  const holdings = fundHoldings(3000001, null)!;
  server.use(
    http.get("/api/funds/:cik/performance", () => HttpResponse.json({ ...performance, points: [], coverage_pct: 0 })),
    http.get("/api/funds/:cik/holdings", () => HttpResponse.json({ ...holdings,
      rows: [{ ...holdings.rows[0], security: { ...holdings.rows[0].security, ticker: null, issuer_cik: null } }], next_cursor: "more" })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37 }))),
  );
  render(<AppWithRouter initialPath="/fund/3000001" />);
  expect(await screen.findByText("No completed quarterly performance yet")).toBeInTheDocument();
  expect(screen.queryByText("No price data for this security.")).not.toBeInTheDocument();
});
