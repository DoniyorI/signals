import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createChart } from "lightweight-charts";
import { AppWithRouter } from "@/App";
import { server } from "@/mocks/node";

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({ addSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
    applyOptions: vi.fn(), remove: vi.fn(), timeScale: vi.fn(() => ({ fitContent: vi.fn() })) })),
  LineSeries: {}, ColorType: { Solid: "solid" },
}));
let requests: URL[] = [];
const record = ({ request }: { request: Request }) => { requests.push(new URL(request.url)); };
beforeEach(() => { requests = []; vi.clearAllMocks(); server.events.on("request:start", record); });
afterEach(() => server.events.removeListener("request:start", record));
const lastCompare = () => requests.filter((r) => r.pathname === "/api/compare").at(-1);

it("requests compare with ids from url and overlays named profile curves", async () => {
  render(<AppWithRouter initialPath="/compare?ids=insider:2000001,fund:3000001" />);
  const table = await screen.findByRole("table", { name: "Profile comparison" });
  expect(lastCompare()?.searchParams.get("ids")).toBe("insider:2000001,fund:3000001");
  expect(lastCompare()?.searchParams.get("basis")).toBe("filed");
  expect(lastCompare()?.searchParams.get("include_10b5_1")).toBe("false");
  expect(within(table).getByRole("link", { name: "Doe Jane" })).toHaveAttribute("href", "/insider/2000001");
  expect(within(table).getByText("Quarterly decisions")).toBeInTheDocument();
  expect(within(table).getByText("Six-month decisions")).toBeInTheDocument();
  await waitFor(() => expect(createChart).toHaveBeenCalled());
  const chart = vi.mocked(createChart).mock.results.at(-1)?.value;
  expect(chart.addSeries).toHaveBeenCalledTimes(2);
  expect(vi.mocked(chart.addSeries).mock.calls.map((c: unknown[]) => (c[1] as { title: string }).title)).toEqual(["Doe Jane", "Example Capital Management"]);
  const styles = vi.mocked(chart.addSeries).mock.calls.map((c: unknown[]) => c[1] as { lineStyle?: number });
  expect(styles[0].lineStyle).not.toBe(styles[1].lineStyle);
});

it("removing a chip updates url and the server request", async () => {
  render(<AppWithRouter initialPath="/compare?ids=insider:2000001,fund:3000001" />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "Remove Doe Jane" }));
  await waitFor(() => expect(lastCompare()?.searchParams.get("ids")).toBe("fund:3000001"));
  expect(screen.queryByRole("button", { name: "Remove Doe Jane" })).not.toBeInTheDocument();
});

it("add disabled at four", async () => {
  render(<AppWithRouter initialPath="/compare?ids=insider:2000001,insider:2000002,fund:3000001,fund:3000002" />);
  expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  expect(screen.getByText("Up to 4 profiles")).toBeInTheDocument();
  await screen.findByRole("table", { name: "Profile comparison" });
});

it("search picker adds an insider without losing the existing fund", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/compare?ids=fund:3000001" />);
  await user.click(screen.getByRole("button", { name: "Add" }));
  await user.type(screen.getByRole("searchbox", { name: "Search profiles" }), "Doe");
  await user.click(await screen.findByRole("button", { name: /Doe Jane.*CEO/ }));
  await waitFor(() => expect(lastCompare()?.searchParams.get("ids")).toBe("fund:3000001,insider:2000001"));
});
