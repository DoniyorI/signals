import { api, type Schema } from "@/api/client";
import openapi from "@/api/openapi.json";
import { resetMockState } from "@/mocks/state";

const url = (path: string) => new URL(path, window.location.origin).toString();

async function getJson<T>(path: string): Promise<{ status: number; body: T }> {
  const res = await fetch(url(path));
  return { status: res.status, body: (await res.json()) as T };
}

it("/api/feed returns page 1, then page 2 through the cursor", async () => {
  const p1 = (await getJson<Schema<"FeedPage">>("/api/feed")).body;
  expect(p1.items).toHaveLength(50);
  expect(p1.next_cursor).toEqual(expect.any(String));
  const accepted = p1.items.map((i) => i.accepted_at ?? "");
  expect(accepted).toEqual([...accepted].sort().reverse());

  const p2 = (
    await getJson<Schema<"FeedPage">>(`/api/feed?cursor=${encodeURIComponent(p1.next_cursor!)}`)
  ).body;
  expect(p2.items.length).toBeGreaterThan(0);
  expect(p2.next_cursor).toBeNull();
  const all = [...p1.items, ...p2.items].map((i) => i.accession_no);
  expect(new Set(all).size).toBe(all.length);
});

it("the default feed view (10b5-1 hidden) still has a second page", async () => {
  const p1 = (await getJson<Schema<"FeedPage">>("/api/feed?include_10b5_1=false&limit=50")).body;
  expect(p1.items).toHaveLength(50);
  expect(p1.items.every((i) => i.plan_10b5_1 === "none" || i.plan_10b5_1 === null)).toBe(true);
  expect(p1.next_cursor).not.toBeNull();
});

it("honors direction on the feed", async () => {
  const page = (await getJson<Schema<"FeedPage">>("/api/feed?direction=buy")).body;
  expect(page.items.length).toBeGreaterThan(0);
  expect(page.items.every((i) => i.direction === "buy")).toBe(true);
});

it("/api/insiders/2000005 has a null rating", async () => {
  const { status, body } = await getJson<Schema<"InsiderHeader">>("/api/insiders/2000005");
  expect(status).toBe(200);
  expect(body.rating.score).toBeNull();
  expect(body.avg_roi_6m).toBeNull();
  expect(body.n_decisions).toBe(1);
});

it("/api/insiders/2000001 is Doe Jane, CEO of Acme, rated 78 high", async () => {
  const { body } = await getJson<Schema<"InsiderHeader">>("/api/insiders/2000001");
  expect(body.name).toBe("Doe Jane");
  expect(body.rating).toMatchObject({ score: 78, confidence: "high" });
  expect(body.roles[0].issuer.cik).toBe(1000001);
  expect(body.roles[0].roles).toContain("CEO");
});

it("/api/funds/3999999/performance has status 404", async () => {
  const { status, body } = await getJson<{ detail: string }>("/api/funds/3999999/performance");
  expect(status).toBe(404);
  expect(body.detail).toBe("performance is available for tracked funds only");
});

it("honors period on fund holdings and basis on performance", async () => {
  const latest = (await getJson<Schema<"FundHoldingsOut">>("/api/funds/3000001/holdings")).body;
  expect(latest.period).toBe("2024-06-30");
  expect(latest.exits.map((r) => r.security.cusip)).toEqual(["000000CC3"]);
  const q1 = (await getJson<Schema<"FundHoldingsOut">>("/api/funds/3000001/holdings?period=2024-03-31"))
    .body;
  expect(q1.period).toBe("2024-03-31");
  expect(q1.exits).toHaveLength(0);

  const filed = (await getJson<Schema<"PerformanceOut">>("/api/insiders/2000001/performance")).body;
  const executed = (
    await getJson<Schema<"PerformanceOut">>("/api/insiders/2000001/performance?basis=executed")
  ).body;
  expect(filed.basis).toBe("filed");
  expect(executed.basis).toBe("executed");
  expect(executed.points.at(-1)!.nav).not.toBe(filed.points.at(-1)!.nav);
});

it("resolves company tickers, including former ones, and 404s unknown refs", async () => {
  const gbx = (await getJson<Schema<"CompanyHeader">>("/api/companies/GBX")).body;
  expect(gbx).toMatchObject({ cik: 1000002, name: "Globex Inc", ticker: "GLBX", former_tickers: ["GBX"] });
  expect((await getJson<Schema<"CompanyHeader">>("/api/companies/acme")).body.cik).toBe(1000001);
  expect((await getJson<Schema<"CompanyHeader">>("/api/companies/XYZ")).body.cik).toBe(1000004);
  expect((await getJson<unknown>("/api/companies/NOPE")).status).toBe(404);
});

it("/api/search?q=ac has at least one company", async () => {
  const { body } = await getJson<Schema<"SearchOut">>("/api/search?q=ac");
  expect(body.companies.length).toBeGreaterThan(0);
  expect(body.companies[0].name).toBe("Acme Corp");
});

it("the typed api client reaches the mocks", async () => {
  const { data, response } = await api.GET("/api/health");
  expect(response.status).toBe(200);
  expect(data?.status).toBe("ok");
});

const SAMPLE_PARAMS: Record<string, string> = {
  cik: "1000001",
  ref: "ACME",
  kind: "company",
};
const SAMPLE_CIK_BY_PREFIX: Record<string, string> = {
  "/api/insiders": "2000001",
  "/api/funds": "3000001",
  "/api/companies": "1000001",
};
const REQUIRED_QUERY: Record<string, string> = {
  "/api/search": "?q=acme",
  "/api/compare": "?ids=insider:2000001",
};
const BODIES: Record<string, unknown> = {
  "/api/watchlists": { name: "Coverage list" },
  "/api/watchlists/{watchlist_id}/items": { kind: "insider", cik: 2000002 },
  "/api/jobs": { kind: "reparse", params: { accessions: ["0001000001-24-000101"] } },
};
// The DELETE endpoints are destructive (they remove the watchlist / item the other requests
// in this sweep rely on), so they get their own small, deterministic tests below instead.
const SKIP_IN_SWEEP = new Set([
  "DELETE /api/watchlists/{watchlist_id}",
  "DELETE /api/watchlists/{watchlist_id}/items/{kind}/{cik}",
]);

it("covers every path and method in the contract", async () => {
  resetMockState();
  const watchlist = (await (
    await fetch(url("/api/watchlists"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Coverage list" }),
    })
  ).json()) as Schema<"WatchlistOut">;
  const misses: string[] = [];
  for (const [template, ops] of Object.entries(openapi.paths)) {
    for (const method of Object.keys(ops)) {
      const key = `${method.toUpperCase()} ${template}`;
      if (SKIP_IN_SWEEP.has(key)) continue;
      const prefix = Object.keys(SAMPLE_CIK_BY_PREFIX).find((p) => template.startsWith(p));
      const path = template.replace(/\{(\w+)\}/g, (_, name: string) => {
        if (name === "watchlist_id") return String(watchlist.id);
        if (name === "cik" && prefix) return SAMPLE_CIK_BY_PREFIX[prefix];
        return SAMPLE_PARAMS[name];
      });
      const body = BODIES[template];
      try {
        const res = await fetch(url(path + (REQUIRED_QUERY[template] ?? "")), {
          method: method.toUpperCase(),
          headers: body ? { "content-type": "application/json" } : undefined,
          body: body ? JSON.stringify(body) : undefined,
        });
        if (!res.ok) misses.push(`${key} -> ${res.status}`);
      } catch (e) {
        misses.push(`${key} -> ${(e as Error).message}`);
      }
    }
  }
  expect(misses).toEqual([]);
});

it("deleting a watchlist, then its item endpoint, both return 204", async () => {
  resetMockState();
  const created = (await (
    await fetch(url("/api/watchlists"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Temp" }),
    })
  ).json()) as Schema<"WatchlistOut">;
  await fetch(url("/api/watchlists/" + created.id + "/items"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind: "insider", cik: 2000001 }),
  });
  const removeItem = await fetch(url(`/api/watchlists/${created.id}/items/insider/2000001`), { method: "DELETE" });
  expect(removeItem.status).toBe(204);
  const del = await fetch(url(`/api/watchlists/${created.id}`), { method: "DELETE" });
  expect(del.status).toBe(204);
  expect((await getJson<unknown>(`/api/watchlists/${created.id}`)).status).toBe(404);
});
