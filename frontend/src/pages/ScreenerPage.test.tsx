import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, expect, it } from "vitest";
import { AppWithRouter } from "@/App";
import { server } from "@/mocks/node";
import { screenInsiders } from "@/mocks/data/screener";
import { coverageFixture } from "@/test/coverage";

let requests: URL[] = [];
function record({ request }: { request: Request }) {
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/screener/")) requests.push(url);
}
beforeEach(() => { requests = []; server.events.on("request:start", record); });
afterEach(() => server.events.removeListener("request:start", record));

it("sort click sends sort and order and retains profile links", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/screener" />);
  expect(await screen.findByRole("link", { name: "Doe Jane" })).toHaveAttribute("href", "/insider/2000001");
  await user.click(screen.getByRole("button", { name: "Avg ROI" }));
  await waitFor(() => expect(requests.at(-1)?.searchParams.get("sort")).toBe("avg_roi_6m"));
  expect(requests.at(-1)?.searchParams.get("order")).toBe("desc");
  await user.click(await screen.findByRole("button", { name: "Avg ROI" }));
  await waitFor(() => expect(requests.at(-1)?.searchParams.get("order")).toBe("asc"));
});

it("role filter sends roles=CEO and hides planned trades by default", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/screener" />);
  await screen.findByRole("link", { name: "Doe Jane" });
  await user.click(screen.getByRole("button", { name: "Filters" }));
  await user.click(screen.getByRole("checkbox", { name: "CEO" }));
  await waitFor(() => expect(requests.at(-1)?.searchParams.getAll("roles")).toEqual(["CEO"]));
  expect(requests.at(-1)?.searchParams.get("include_10b5_1")).toBe("false");
});

it("funds tab requests /api/screener/funds with tracked funds by default", async () => {
  render(<AppWithRouter initialPath="/screener" />);
  await userEvent.setup().click(screen.getByRole("tab", { name: "Funds" }));
  expect(await screen.findByRole("link", { name: "Example Capital Management" })).toHaveAttribute("href", "/fund/3000001");
  expect(requests.at(-1)?.pathname).toBe("/api/screener/funds");
  expect(requests.at(-1)?.searchParams.get("tracked_only")).toBe("true");
});

it("restores URL filters and includes them in the CSV export", async () => {
  render(<AppWithRouter initialPath="/screener?roles=CEO&basis=executed&window=3y&min_return=0.1&sort=return&order=asc" />);
  const csv = await screen.findByRole("link", { name: "Export CSV" });
  const query = new URL(csv.getAttribute("href")!, "http://localhost").searchParams;
  expect(query.getAll("roles")).toEqual(["CEO"]);
  expect(query.get("basis")).toBe("executed");
  expect(query.get("window")).toBe("3y");
  expect(query.get("min_return")).toBe("0.1");
  expect(query.get("format")).toBe("csv");
});

it("loads another cursor page without losing the existing rows", async () => {
  const rows = screenInsiders(new URLSearchParams("include_10b5_1=false"));
  server.use(http.get("/api/screener/insiders", ({ request }) => {
    const next = new URL(request.url).searchParams.get("cursor");
    return HttpResponse.json({ items: [rows[next ? 1 : 0]], next_cursor: next ? null : "page-two" });
  }));
  render(<AppWithRouter initialPath="/screener" />);
  await screen.findByRole("link", { name: rows[0].owner.name });
  await userEvent.setup().click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByRole("link", { name: rows[1].owner.name })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: rows[0].owner.name })).toBeInTheDocument();
  expect(requests.at(-1)?.searchParams.get("cursor")).toBe("page-two");
});

it("validates integer rating filters before requesting the server", async () => {
  render(<AppWithRouter initialPath="/screener?min_rating=40.5" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Minimum rating must be a whole number from 0 to 100");
  expect(requests).toHaveLength(0);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Filters" }));
  const rating = screen.getByRole("spinbutton", { name: "Minimum rating" });
  await user.clear(rating);
  await user.type(rating, "40");
  await waitFor(() => expect(requests.at(-1)?.searchParams.get("min_rating")).toBe("40"));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("every displayed insider and fund column exposes server sorting", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/screener" />);
  await screen.findByRole("link", { name: "Doe Jane" });
  for (const header of ["Insider", "Company", "Roles", "Sector", "Rating", "Avg ROI", "Hit rate", "Decisions", "Last trade", "1Y return", "Risk"]) {
    expect(screen.getByRole("button", { name: header })).toBeInTheDocument();
  }
  await user.click(screen.getByRole("button", { name: "Insider" }));
  await waitFor(() => expect(requests.at(-1)?.searchParams.get("sort")).toBe("owner"));
  await user.click(screen.getByRole("tab", { name: "Funds" }));
  await screen.findByRole("link", { name: "Example Capital Management" });
  for (const header of ["Fund", "Portfolio value", "Positions", "Top sector", "Rating (quarterly)", "1Y return", "Risk", "Coverage"]) {
    expect(screen.getByRole("button", { name: header })).toBeInTheDocument();
  }
  await user.click(screen.getByRole("button", { name: "Coverage" }));
  await waitFor(() => expect(requests.at(-1)?.searchParams.get("sort")).toBe("coverage_pct"));
});

it("screener empty state explains prices still loading", async () => {
  server.use(
    http.get("/api/screener/insiders", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37 }))),
  );
  render(<AppWithRouter initialPath="/screener" />);
  expect(await screen.findByText("Performance appears when prices finish loading (37% done).")).toBeInTheDocument();
});

it("keeps genuine filter misses distinct from loading prices", async () => {
  server.use(http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37 }))));
  render(<AppWithRouter initialPath="/screener?min_rating=100" />);
  expect(await screen.findByText("No insiders match these filters")).toBeInTheDocument();
  expect(screen.queryByText(/Performance appears when prices finish loading/)).not.toBeInTheDocument();
});

it("does not claim prices are loading just because price coverage is low", async () => {
  server.use(
    http.get("/api/screener/insiders", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ pct: 0.37 }))),
  );
  render(<AppWithRouter initialPath="/screener" />);
  expect(await screen.findByText("No insider performance data yet")).toBeInTheDocument();
  expect(screen.queryByText(/Performance appears when prices finish loading/)).not.toBeInTheDocument();
});

it("shows a coverage error instead of inventing an empty reason", async () => {
  server.use(
    http.get("/api/screener/insiders", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get("/api/health/completeness", () => HttpResponse.json({ detail: "unavailable" }, { status: 500 })),
  );
  render(<AppWithRouter initialPath="/screener" />);
  expect(await screen.findByText("Coverage details didn't load", {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.queryByText(/Performance appears when prices finish loading/)).not.toBeInTheDocument();
});

it("does not treat ignored insider filters as fund filter misses", async () => {
  server.use(
    http.get("/api/screener/funds", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0.37 }))),
  );
  render(<AppWithRouter initialPath="/screener?tab=funds&roles=CEO" />);
  expect(await screen.findByText("Performance appears when prices finish loading (37% done).")).toBeInTheDocument();
});
