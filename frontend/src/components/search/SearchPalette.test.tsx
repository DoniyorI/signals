import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppWithRouter } from "@/App";
import { server } from "@/mocks/node";
import type { Schema } from "@/api/client";

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({ addSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
    applyOptions: vi.fn(), remove: vi.fn(), timeScale: vi.fn(() => ({ fitContent: vi.fn() })) })),
  LineSeries: {}, CandlestickSeries: {}, AreaSeries: {}, createSeriesMarkers: vi.fn(), ColorType: { Solid: "solid" },
}));

const fixture: Schema<"SearchOut"> = {
  companies: [{ kind: "company", cik: 1000001, name: "Acme Corp", ticker: "ACME", subtitle: "ACME · Technology", score: 4 }],
  insiders: [{ kind: "insider", cik: 2000001, name: "Doe Jane", ticker: null, subtitle: "CEO · Acme Corp", score: 3 }],
  funds: [{ kind: "fund", cik: 3000001, name: "Example Capital Management", ticker: null, subtitle: "13F filer", score: 2 }],
};
let searches: string[] = [];
beforeEach(() => {
  searches = [];
  server.use(http.get("/api/search", ({ request }) => {
    searches.push(new URL(request.url).searchParams.get("q")!);
    return HttpResponse.json(fixture);
  }));
});
afterEach(() => vi.useRealTimers());

it("opens with keyboard shortcut and Esc closes it", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/screener" />);
  await user.keyboard("{Control>}k{/Control}");
  expect(await screen.findByRole("dialog", { name: "Search profiles" })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await user.keyboard("{Meta>}k{/Meta}");
  expect(await screen.findByRole("dialog", { name: "Search profiles" })).toBeInTheDocument();
});

it("debounced search shows groups and preserves server-ranked matches", async () => {
  render(<AppWithRouter initialPath="/screener" />);
  await userEvent.setup().click(screen.getByRole("button", { name: /Search/ }));
  const input = screen.getByRole("combobox", { name: "Search profiles" });
  vi.useFakeTimers();
  fireEvent.change(input, { target: { value: "a" } });
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(searches).toEqual([]);
  fireEvent.change(input, { target: { value: "ac" } });
  await act(() => vi.advanceTimersByTimeAsync(199));
  expect(searches).toEqual([]);
  await act(() => vi.advanceTimersByTimeAsync(1));
  await act(async () => {
    await vi.waitFor(() => expect(screen.getByText("Acme Corp")).toBeInTheDocument());
  });
  vi.useRealTimers();
  expect(searches).toEqual(["ac"]);
  const palette = within(screen.getByRole("dialog", { name: "Search profiles" }));
  for (const heading of ["Companies", "Insiders", "Funds"]) expect(palette.getByText(heading)).toBeInTheDocument();
  expect(palette.getByText("Doe Jane")).toBeInTheDocument();
  expect(palette.getByText("CEO · Acme Corp")).toBeInTheDocument();
});

it("enter navigates to company", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/screener" />);
  await user.keyboard("{Control>}k{/Control}");
  await user.type(screen.getByRole("combobox", { name: "Search profiles" }), "ac");
  await screen.findByRole("option", { name: /^Acme Corp/ });
  await user.keyboard("{Enter}");
  expect(await screen.findByRole("heading", { name: /Acme Corp/ })).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("navigates an insider and a fund by CIK", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/screener" />);
  await user.click(screen.getByRole("button", { name: /Search/ }));
  await user.type(screen.getByRole("combobox", { name: "Search profiles" }), "ac");
  await user.click(await screen.findByRole("option", { name: /Doe Jane/ }));
  expect(await screen.findByRole("heading", { name: "Doe Jane" })).toBeInTheDocument();
  await user.keyboard("{Control>}k{/Control}");
  await user.type(screen.getByRole("combobox", { name: "Search profiles" }), "ac");
  await user.click(await screen.findByRole("option", { name: /Example Capital Management/ }));
  expect(await screen.findByRole("heading", { name: "Example Capital Management" })).toBeInTheDocument();
});
