import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AppWithRouter } from "@/App";

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
