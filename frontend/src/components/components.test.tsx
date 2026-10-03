import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NOT_ENOUGH_DATA } from "@/lib/format";
import { AllocationDonut } from "./charts/AllocationDonut";
import { EquityChart } from "./charts/EquityChart";
import { PriceChart } from "./charts/PriceChart";
import { ValueChart } from "./charts/ValueChart";
import { BadgeChip } from "./data/BadgeChip";
import { ChangeChip } from "./data/ChangeChip";
import { DataTable } from "./data/DataTable";
import { PlanChip } from "./data/PlanChip";
import { RatingPill } from "./data/RatingPill";
import { ReturnCell } from "./data/ReturnCell";
import { WindowsTable } from "./data/WindowsTable";

// lightweight-charts draws on canvas, which jsdom doesn't implement; every chart built on it
// gets a minimal stub so mounting can be verified without a real canvas.
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

function withTooltips(ui: React.ReactNode) {
  return <TooltipProvider>{ui}</TooltipProvider>;
}

describe("BadgeChip", () => {
  it("shows the badge label", () => {
    render(withTooltips(<BadgeChip badge="cluster_buy" />));
    expect(screen.getByText("Cluster buy")).toBeInTheDocument();
  });
});

describe("RatingPill", () => {
  it("shows 'Not enough data yet' for a null score", () => {
    render(<RatingPill rating={{ score: null, confidence: null, n: 0 }} />);
    expect(screen.getByText(NOT_ENOUGH_DATA)).toBeInTheDocument();
    expect(screen.getByText("Rating appears after completed six-month returns are calculated.")).toBeInTheDocument();
  });

  it("shows the score and confidence otherwise", () => {
    render(<RatingPill rating={{ score: 78, confidence: "high", n: 4 }} />);
    expect(screen.getByText("78 · High")).toBeInTheDocument();
  });
});

describe("ReturnCell", () => {
  it("renders -5.0% with the negative class", () => {
    render(<ReturnCell value={-0.05} />);
    const el = screen.getByText("-5.0%");
    expect(el).toHaveClass("text-neg");
  });

  it("renders a positive value with the positive class", () => {
    render(<ReturnCell value={0.05} />);
    expect(screen.getByText("+5.0%")).toHaveClass("text-pos");
  });

  it("renders the dash for null", () => {
    render(<ReturnCell value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("PlanChip", () => {
  it("renders nothing for 'none'", () => {
    const { container } = render(<PlanChip flag="none" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the plan label otherwise", () => {
    render(<PlanChip flag="flag" />);
    expect(screen.getByText("10b5-1 plan")).toBeInTheDocument();
  });
});

describe("ChangeChip", () => {
  it.each([
    ["NEW", "New"],
    ["ADD", "Add"],
    ["TRIM", "Trim"],
    ["EXIT", "Exit"],
    ["SAME", "Same"],
  ] as const)("labels %s as %s", (change, label) => {
    render(<ChangeChip change={change} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("WindowsTable", () => {
  it("renders — for a missing window and the vs-SPY difference otherwise", () => {
    render(
      <WindowsTable
        windows={[
          { window: "ytd", ret: 0.11, ret_spy: 0.10, ret_qqq: null, ret_sector: null, annualized: null, vol: null, max_drawdown: null, beta: null, time_invested_pct: null },
        ]}
      />,
    );
    // YTD row: vs SPY = 0.11 - 0.10 = +1.0%.
    expect(screen.getByText("+1.0%")).toBeInTheDocument();
    // 1Y/3Y/5Y rows are entirely absent from `windows`, so every cell in them is the dash.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("PriceChart", () => {
  it("mounts without throwing when lightweight-charts is replaced by a stub", () => {
    expect(() =>
      render(
        <PriceChart
          bars={[{ date: "2024-06-03", open: 1, high: 2, low: 0.5, close: 1.5, adj_close: 1.5, volume: 100 }]}
          markers={[{ date: "2024-06-03", kind: "buy", label: "Bought", value_usd: 1, ref: "a" }]}
        />,
      ),
    ).not.toThrow();
  });
});

describe("EquityChart", () => {
  it("mounts without throwing and shows a legend for multiple series", () => {
    expect(() =>
      render(
        <EquityChart
          points={[
            { date: "2024-06-03", nav: 1.0, spy: 1.0, qqq: 1.0, sector: 1.0 },
            { date: "2024-06-04", nav: 1.02, spy: 1.01, qqq: 1.01, sector: 1.0 },
          ]}
        />,
      ),
    ).not.toThrow();
    expect(screen.getByText("This portfolio")).toBeInTheDocument();
    expect(screen.getByText("S&P 500")).toBeInTheDocument();
  });

  it("hides a series (and its legend entry) when show sets it false", () => {
    render(
      <EquityChart
        points={[{ date: "2024-06-03", nav: 1.0, spy: 1.0, qqq: 1.0, sector: 1.0 }]}
        show={{ qqq: false, sector: false }}
      />,
    );
    expect(screen.queryByText("Nasdaq 100")).not.toBeInTheDocument();
    expect(screen.getByText("This portfolio")).toBeInTheDocument();
  });
});

describe("ValueChart", () => {
  it("mounts without throwing", () => {
    expect(() =>
      render(<ValueChart points={[{ period: "2024-03-31", value_usd: 1000, positions: 2 }]} />),
    ).not.toThrow();
  });
});

describe("AllocationDonut", () => {
  it("collapses beyond the top 8 into Other and lists every slice's weight", () => {
    const slices = Array.from({ length: 9 }, (_, i) => ({
      key: `s${i}`,
      label: `Sector ${i}`,
      value_usd: 100 - i,
      weight: 0.1,
    }));
    render(<AllocationDonut slices={slices} />);
    expect(screen.getByText("Other")).toBeInTheDocument();
    expect(screen.getByText("Sector 0")).toBeInTheDocument();
    expect(screen.queryByText("Sector 8")).not.toBeInTheDocument();
  });

  it("shows a placeholder for no holdings", () => {
    render(<AllocationDonut slices={[]} />);
    expect(screen.getByText("No holdings to show.")).toBeInTheDocument();
  });
});

interface Row {
  id: string;
  name: string;
  value: number;
}

const ROWS: Row[] = [
  { id: "a", name: "Acme", value: 3 },
  { id: "b", name: "Beta", value: 1 },
  { id: "c", name: "Gamma", value: 2 },
];

const COLUMNS = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "value", header: "Value" },
];

describe("DataTable", () => {
  it("renders every row", () => {
    render(<DataTable columns={COLUMNS} data={ROWS} getRowId={(r) => r.id} />);
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });

  it("sorts the loaded rows when a sortable header is clicked", async () => {
    const user = userEvent.setup();
    render(<DataTable columns={COLUMNS} data={ROWS} getRowId={(r) => r.id} />);
    const firstDataRow = () => screen.getAllByRole("row")[1].textContent;
    await user.click(screen.getByText("Value"));
    expect(firstDataRow()).toContain("Acme"); // a numeric column's first click is descending (value 3)
    await user.click(screen.getByText("Value"));
    expect(firstDataRow()).toContain("Beta"); // second click flips to ascending (value 1)
  });

  it("renders the empty state when there are no rows", () => {
    render(<DataTable columns={COLUMNS} data={[]} getRowId={(r: Row) => r.id} empty="No rows match these filters" />);
    expect(screen.getByText("No rows match these filters")).toBeInTheDocument();
  });

  it("calls onEndReached when the scroll container nears the bottom", () => {
    const onEndReached = vi.fn();
    const { container } = render(
      <DataTable columns={COLUMNS} data={ROWS} getRowId={(r) => r.id} onEndReached={onEndReached} />,
    );
    const scrollEl = container.querySelector(".overflow-auto")!;
    Object.defineProperty(scrollEl, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(scrollEl, "clientHeight", { value: 400, configurable: true });
    Object.defineProperty(scrollEl, "scrollTop", { value: 650, configurable: true }); // 1000-650-400 = -50 < 200
    scrollEl.dispatchEvent(new Event("scroll"));
    expect(onEndReached).toHaveBeenCalledTimes(1);
  });

  it("also renders a Load more button, for a first page too short to scroll", async () => {
    const user = userEvent.setup();
    const onEndReached = vi.fn();
    render(<DataTable columns={COLUMNS} data={ROWS} getRowId={(r) => r.id} onEndReached={onEndReached} />);
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(onEndReached).toHaveBeenCalledTimes(1);
  });
});
