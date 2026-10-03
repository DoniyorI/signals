import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "../src/api/schema";

type Schema<K extends keyof components["schemas"]> = components["schemas"][K];
const real = Boolean(process.env.E2E_BASE_URL);

async function get<K extends keyof components["schemas"]>(request: APIRequestContext, path: string): Promise<Schema<K>> {
  const response = await request.get(path);
  expect(response.ok(), `${path}: HTTP ${response.status()}`).toBeTruthy();
  return response.json() as Promise<Schema<K>>;
}

test.describe("historical data acceptance", () => {
  test.skip(!real, "Requires E2E_BASE_URL and the completed real backfill; fixtures do not prove coverage");
  test.setTimeout(120_000);

  test("LEN has insider trades in every historical year and correct trailing net", async ({ page, request }) => {
    const company = await get<"CompanyHeader">(request, "/api/companies/LEN");
    const history = await get<"PriceSeriesOut">(request, `/api/companies/${company.cik}/prices?start=2016-01-01&markers=true`);
    const trades = history.markers.filter((marker) => marker.kind === "buy" || marker.kind === "sell");
    const years = new Set(trades.map((marker) => Number(marker.date.slice(0, 4))));
    const currentYear = Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric" }).format(new Date()));
    for (let year = 2016; year <= currentYear; year++) {
      expect(years.has(year), `LEN missing open-market trades in ${year}`).toBeTruthy();
    }
    // Ask the same calendar-date window as the header, independently summing trade markers.
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
    const start = new Date(`${today}T12:00:00Z`);
    start.setUTCDate(start.getUTCDate() - 365);
    const startDay = start.toISOString().slice(0, 10);
    const recent = trades.filter((marker) => marker.date >= startDay && marker.date <= today);
    const expectedNet = recent.reduce((sum, marker) => sum + (marker.value_usd ?? 0) * (marker.kind === "buy" ? 1 : -1), 0);
    const net = company.net_buying.find((window) => window.window === "12m");
    expect(net).toBeDefined();
    expect(net!.net_usd).toBeCloseTo(expectedNet, 2);
    if (expectedNet !== 0) expect(net!.net_usd).not.toBe(0);
    await page.goto("/company/LEN");
    await expect(page.getByRole("heading", { level: 1, name: company.name })).toBeVisible();
    await expect(page.getByText("12m net", { exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Net (12m)", exact: true })).toBeVisible();
    await expect(page.locator("tbody tr").first()).toBeVisible();
  });

  test("default insider screener contains at least 100 distinct insiders", async ({ page, request }) => {
    const result = await get<"InsiderScreenPage">(request, "/api/screener/insiders?limit=100");
    expect(new Set(result.items.map((item) => item.owner.cik)).size).toBeGreaterThanOrEqual(100);
    await page.goto("/screener");
    await expect(page.getByRole("heading", { level: 1, name: "Screener" })).toBeVisible();
    await expect(page.getByRole("link", { name: result.items[0].owner.name, exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Load more", exact: true })).toBeVisible();
  });

  test("a mature insider has curves and window results on both return bases", async ({ page, request }) => {
    const candidates = await get<"InsiderScreenPage">(request, "/api/screener/insiders?min_decisions=3&limit=100");
    let chosen: Schema<"InsiderScreenRow"> | undefined;
    for (const candidate of candidates.items.filter((item) => item.rating.n >= 3)) {
      const executed = await get<"InsiderHeader">(request, `/api/insiders/${candidate.owner.cik}?basis=executed`);
      if (executed.rating.n >= 3) { chosen = candidate; break; }
    }
    expect(chosen, "No insider has three completed decisions on both bases").toBeDefined();
    const cik = chosen!.owner.cik;
    await page.goto(`/insider/${cik}`);
    for (const [basis, label] of [["filed", "From filing"], ["executed", "From trade"]] as const) {
      await page.getByRole("radio", { name: label, exact: true }).click();
      const performance = await get<"PerformanceOut">(request, `/api/insiders/${cik}/performance?basis=${basis}`);
      expect(performance.points.length).toBeGreaterThan(1);
      expect(performance.windows.some((window) => window.ret != null)).toBeTruthy();
      await expect(page.getByText("This portfolio", { exact: true })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "vs SPY", exact: true })).toBeVisible();
      await expect(page.locator("canvas").first()).toBeVisible();
      const windows = page.getByRole("table").filter({ has: page.getByRole("columnheader", { name: "Window", exact: true }) });
      await expect(windows.getByRole("cell", { name: "1Y", exact: true })).toBeVisible();
      await expect(windows.getByRole("cell").filter({ hasText: /\d.*%/ }).first()).toBeVisible();
    }
  });

  test("tracked funds screener has at least 20 funds with quarterly metrics", async ({ page, request }) => {
    const result = await get<"FundScreenPage">(request, "/api/screener/funds?tracked_only=true&limit=100");
    const populated = result.items.filter((item) => item.rating.n > 0 && item.windows["1y"] != null);
    expect(new Set(populated.map((item) => item.fund.cik)).size).toBeGreaterThanOrEqual(20);
    await page.goto("/screener?tab=funds");
    await expect(page.getByRole("columnheader", { name: "Rating (quarterly)" })).toBeVisible();
    await expect(page.getByText("Fund ratings use quarterly excess returns.", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: populated[0].fund.name, exact: true }).first()).toBeVisible();
  });
});
