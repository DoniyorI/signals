import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppWithRouter } from "@/App";
import { HttpResponse, http } from "msw";
import { server } from "@/mocks/node";
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

let requestUrls: string[] = [];

function onRequestStart({ request }: { request: Request }) {
  requestUrls.push(request.url);
}

beforeEach(() => {
  requestUrls = [];
  server.events.on("request:start", onRequestStart);
});

afterEach(() => {
  server.events.removeListener("request:start", onRequestStart);
});

it("shows former ticker", async () => {
  render(<AppWithRouter initialPath="/company/GBX" />);
  expect(await screen.findByRole("heading", { name: "Globex Inc" })).toBeInTheDocument();
  expect(await screen.findByText("formerly GBX")).toBeInTheDocument();
});

it("quarter select requests period", async () => {
  render(<AppWithRouter initialPath="/company/ACME" />);
  await screen.findByRole("heading", { name: "Acme Corp" });
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "Institutions" }));
  await user.click(await screen.findByRole("combobox"));
  await user.click(await screen.findByText("Mar 31, 2024"));
  await waitFor(() =>
    expect(requestUrls.some((u) => u.includes("/institutions") && u.includes("period=2024-03-31"))).toBe(true),
  );
});

it("change chips render", async () => {
  render(<AppWithRouter initialPath="/company/ACME" />);
  await screen.findByRole("heading", { name: "Acme Corp" });
  await userEvent.setup().click(screen.getByRole("tab", { name: "Institutions" }));
  expect((await screen.findAllByText("New")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Exit").length).toBeGreaterThan(0);
});

it("unknown company shows not found", async () => {
  render(<AppWithRouter initialPath="/company/NOPE" />);
  expect(await screen.findByText("Company not found")).toBeInTheDocument();
});

it("an unmapped security explains missing prices even during a global price load", async () => {
  server.use(
    http.get("/api/companies/:cik/prices", () => HttpResponse.json({ symbol: null, bars: [], markers: [] })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37 }))),
  );
  render(<AppWithRouter initialPath="/company/ACME" />);
  expect(await screen.findByText("No price data for this security.")).toBeInTheDocument();
  expect(screen.queryByText(/Performance appears when prices finish loading/)).not.toBeInTheDocument();
});

it("shows a price API error instead of hiding the chart", async () => {
  server.use(http.get("/api/companies/:cik/prices", () => HttpResponse.json({ detail: "unavailable" }, { status: 500 })));
  render(<AppWithRouter initialPath="/company/ACME" />);
  expect(await screen.findByText("Prices didn't load", {}, { timeout: 3000 })).toBeInTheDocument();
});
