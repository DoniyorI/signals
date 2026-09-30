import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppWithRouter } from "@/App";
import { server } from "@/mocks/node";

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
});

it("renders not-enough-data state", async () => {
  render(<AppWithRouter initialPath="/insider/2000005" />);
  await screen.findByRole("heading", { name: "New Person" });
  expect(await screen.findByText("Not enough data yet")).toBeInTheDocument();
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
