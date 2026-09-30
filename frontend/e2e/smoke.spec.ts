import { expect, test } from "@playwright/test";

const routes = [
  { path: "/", heading: "Live feed" },
  { path: "/insider/2000001", heading: "Doe Jane" },
  { path: "/company/ACME", heading: /Acme Corp/ },
  { path: "/fund/3000001", heading: "Example Capital Management" },
  { path: "/screener", heading: "Screener" },
  { path: "/compare?ids=insider:2000001,fund:3000001", heading: "Compare" },
  { path: "/watchlists", heading: "Watchlists" },
  { path: "/health", heading: "Data health" },
];

for (const route of routes) {
  test(`renders ${route.path} without console errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(route.path);
    await expect(page.getByRole("heading", { name: route.heading, level: 1 })).toBeVisible();
    await expect(page.getByText("Data from SEC EDGAR. Not investment advice.", { exact: true })).toBeVisible();
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    // Readiness includes all queries and charts, not just a static route title.
    await expect(page.getByText(/^Loading(?:…| data health…| profile…)?$/)).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(errors).toEqual([]);
  });
}

for (const path of ["/", "/insider/2000001"]) {
  test(`phone has no page overflow at ${path}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
}

test("search shortcut navigates to a profile and theme switches", async ({ page }) => {
  await page.goto("/screener");
  await expect(page.getByRole("heading", { name: "Screener", level: 1 })).toBeVisible();
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Search profiles" });
  await expect(palette).toBeVisible();
  await palette.getByRole("combobox", { name: "Search profiles" }).fill("ac");
  await palette.getByRole("option", { name: /^Acme Corp/ }).click();
  await expect(page).toHaveURL(/\/company\/ACME$/);
  await expect(page.getByRole("heading", { level: 1, name: /Acme Corp/ })).toBeVisible();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("screener role filter stays selected after navigation and reload", async ({ page }) => {
  await page.goto("/screener");
  await expect(page.getByRole("link", { name: "Doe Jane" })).toBeVisible();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const ceo = page.getByRole("checkbox", { name: "CEO", exact: true });
  await ceo.click();
  await expect(page).toHaveURL(/roles=CEO/);
  await expect(ceo).toBeChecked();
  await expect(page.getByRole("link", { name: "Doe Jane" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await expect(ceo).toBeChecked();
});
