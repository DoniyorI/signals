import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/api/client";
import { companyForm144, companyHeader, companyInstitutions, companyPrices, companyRoster, companyStakes, lookupCompany } from "./data/companies";
import { compare } from "./data/compare";
import { FEED, feedSummary, filterFeed } from "./data/feed";
import { fundHeader, fundHoldings, fundPerformance } from "./data/funds";
import { health } from "./data/health";
import { insiderDecisions, insiderForm144, insiderHeader, insiderHoldings, insiderPerformance, insiderTransactions } from "./data/insiders";
import { screenFunds, screenInsiders } from "./data/screener";
import { search } from "./data/search";
import { issuerInfo } from "./data/world";
import {
  addWatchlistItem,
  createJob,
  createWatchlist,
  deleteWatchlist,
  getWatchlist,
  listJobs,
  listWatchlists,
  removeWatchlistItem,
} from "./state";

type Basis = "filed" | "executed";
type Page<T> = { items: T[]; next_cursor: string | null };

// ---------------------------------------------------------------- pagination and CSV
/** Opaque to callers: just an offset into an already-sorted array. */
function encodeCursor(offset: number): string {
  return btoa(String(offset));
}

function decodeCursor(cursor: string | null): number {
  if (!cursor) return 0;
  const n = Number(atob(cursor));
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function paginate<T>(items: T[], sp: URLSearchParams): Page<T> {
  const limit = Math.min(Number(sp.get("limit") ?? 50) || 50, 500);
  const offset = decodeCursor(sp.get("cursor"));
  const page = items.slice(offset, offset + limit);
  return { items: page, next_cursor: offset + limit < items.length ? encodeCursor(offset + limit) : null };
}

function flatten(value: unknown, prefix = ""): Record<string, string> {
  if (value === null || value === undefined) return { [prefix]: "" };
  if (Array.isArray(value)) {
    return { [prefix]: value.map((v) => (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v))).join(";") };
  }
  if (typeof value === "object") {
    return Object.assign(
      {},
      ...Object.entries(value as Record<string, unknown>).map(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k)),
    );
  }
  return { [prefix]: String(value) };
}

function toCsv(rows: unknown[]): string {
  if (rows.length === 0) return "";
  const flatRows = rows.map((r) => flatten(r));
  const headers = [...new Set(flatRows.flatMap((r) => Object.keys(r)))];
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return [headers.join(","), ...flatRows.map((r) => headers.map((h) => cell(r[h] ?? "")).join(","))].join("\n");
}

/** Returns a page as JSON, or `format=csv` as a flattened CSV of its rows. */
function respondList<T>(sp: URLSearchParams, rows: T[], filename: string) {
  if (sp.get("format") === "csv") {
    return new HttpResponse(toCsv(rows), {
      headers: { "content-type": "text/csv", "content-disposition": `attachment; filename="${filename}"` },
    });
  }
  return HttpResponse.json(rows);
}

function respondPage<T>(sp: URLSearchParams, rows: T[], filename: string) {
  if (sp.get("format") === "csv") return respondList(sp, rows, filename);
  return HttpResponse.json(paginate(rows, sp));
}

const notFound = (detail: string) => HttpResponse.json({ detail }, { status: 404 });

function basisOf(sp: URLSearchParams): Basis {
  return sp.get("basis") === "executed" ? "executed" : "filed";
}

/** Hide-10b5-1 defaults ON (`?include_10b5_1=false`); anything but the literal "false" shows it. */
function includeOf(sp: URLSearchParams): boolean {
  return sp.get("include_10b5_1") !== "false";
}

export const handlers: HttpHandler[] = [
  // ---------------------------------------------------------------- companies
  http.get("/api/companies/:cik/form144", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const rows = companyForm144(Number(params.cik), sp.get("status"));
    return respondList(sp, rows, "form144.csv");
  }),
  http.get("/api/companies/:cik/insiders", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const rows = companyRoster(Number(params.cik), includeOf(sp));
    return respondList(sp, rows, "insiders.csv");
  }),
  http.get("/api/companies/:cik/institutions", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const out = companyInstitutions(Number(params.cik), sp.get("period"));
    if (sp.get("format") === "csv") return respondList(sp, out.rows, "institutions.csv");
    const { items, next_cursor } = paginate(out.rows, sp);
    return HttpResponse.json({ ...out, rows: items, next_cursor });
  }),
  http.get("/api/companies/:cik/prices", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const info = issuerInfo(Number(params.cik));
    if (!info) return HttpResponse.json({ symbol: null, bars: [], markers: [] });
    return HttpResponse.json(companyPrices(info, sp.get("start"), sp.get("end"), sp.get("markers") !== "false"));
  }),
  http.get("/api/companies/:cik/stakes", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const rows = companyStakes(Number(params.cik), sp.get("current_only") === "true");
    return respondList(sp, rows, "stakes.csv");
  }),
  http.get("/api/companies/:ref", ({ params }) => {
    const info = lookupCompany(String(params.ref));
    if (!info) return notFound("company not found");
    return HttpResponse.json(companyHeader(info));
  }),

  // ---------------------------------------------------------------- compare
  http.get("/api/compare", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const ids = sp.get("ids");
    if (!ids) return HttpResponse.json({ detail: "ids is required" }, { status: 422 });
    return HttpResponse.json(compare(ids, basisOf(sp), includeOf(sp)));
  }),

  // ---------------------------------------------------------------- feed
  http.get("/api/feed", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    return respondPage(sp, filterFeed(FEED, sp), "feed.csv");
  }),
  http.get("/api/feed/summary", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    return HttpResponse.json(feedSummary(sp.get("date") ?? "2024-06-07"));
  }),

  // ---------------------------------------------------------------- funds
  http.get("/api/funds/:cik", ({ params }) => {
    const header = fundHeader(Number(params.cik));
    return header ? HttpResponse.json(header) : notFound("fund not found");
  }),
  http.get("/api/funds/:cik/holdings", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const out = fundHoldings(Number(params.cik), sp.get("period"));
    if (!out) return notFound("fund not found");
    if (sp.get("format") === "csv") return respondList(sp, out.rows, "holdings.csv");
    const { items, next_cursor } = paginate(out.rows, sp);
    return HttpResponse.json({ ...out, rows: items, next_cursor });
  }),
  http.get("/api/funds/:cik/performance", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const out = fundPerformance(Number(params.cik), basisOf(sp));
    return out ? HttpResponse.json(out) : notFound("performance is available for tracked funds only");
  }),

  // ---------------------------------------------------------------- health
  http.get("/api/health", () => HttpResponse.json(health())),

  // ---------------------------------------------------------------- insiders
  http.get("/api/insiders/:cik", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const header = insiderHeader(Number(params.cik), basisOf(sp), includeOf(sp));
    return header ? HttpResponse.json(header) : notFound("insider not found");
  }),
  http.get("/api/insiders/:cik/decisions", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const rows = insiderDecisions(Number(params.cik), basisOf(sp), includeOf(sp), sp.get("direction"));
    return respondPage(sp, rows, "decisions.csv");
  }),
  http.get("/api/insiders/:cik/form144", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    return respondList(sp, insiderForm144(Number(params.cik)), "form144.csv");
  }),
  http.get("/api/insiders/:cik/holdings", ({ params }) => HttpResponse.json(insiderHoldings(Number(params.cik)))),
  http.get("/api/insiders/:cik/performance", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    return HttpResponse.json(insiderPerformance(Number(params.cik), basisOf(sp), includeOf(sp)));
  }),
  http.get("/api/insiders/:cik/transactions", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const codes = sp.getAll("codes").filter(Boolean);
    const issuerCik = sp.get("issuer_cik") ? Number(sp.get("issuer_cik")) : null;
    let rows = insiderTransactions(Number(params.cik), sp.get("include_superseded") === "true");
    if (codes.length) rows = rows.filter((t) => t.code !== null && codes.includes(t.code));
    if (issuerCik !== null) rows = rows.filter((t) => t.issuer.cik === issuerCik);
    return respondPage(sp, rows, "transactions.csv");
  }),

  // ---------------------------------------------------------------- jobs
  http.get("/api/jobs", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    return HttpResponse.json(listJobs(Number(sp.get("limit") ?? 50)));
  }),
  http.post("/api/jobs", async ({ request }) => {
    const body = (await request.json()) as Schema<"JobRequestIn">;
    return HttpResponse.json(createJob(body.kind), { status: 202 });
  }),

  // ---------------------------------------------------------------- screener
  http.get("/api/screener/funds", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    return respondPage(sp, screenFunds(sp), "funds.csv");
  }),
  http.get("/api/screener/insiders", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    return respondPage(sp, screenInsiders(sp), "insiders.csv");
  }),

  // ---------------------------------------------------------------- search
  http.get("/api/search", ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const q = sp.get("q") ?? "";
    if (!q) return HttpResponse.json({ detail: "q is required" }, { status: 422 });
    return HttpResponse.json(search(q, sp.get("limit") ? Number(sp.get("limit")) : undefined));
  }),

  // ---------------------------------------------------------------- watchlists (stateful)
  http.get("/api/watchlists", () => HttpResponse.json(listWatchlists())),
  http.post("/api/watchlists", async ({ request }) => {
    const body = (await request.json()) as Schema<"WatchlistCreate">;
    return HttpResponse.json(createWatchlist(body.name), { status: 201 });
  }),
  http.get("/api/watchlists/:watchlist_id", ({ params }) => {
    const watchlist = getWatchlist(Number(params.watchlist_id));
    return watchlist ? HttpResponse.json(watchlist) : notFound("watchlist not found");
  }),
  http.delete("/api/watchlists/:watchlist_id", ({ params }) => {
    deleteWatchlist(Number(params.watchlist_id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/watchlists/:watchlist_id/activity", ({ request, params }) => {
    const sp = new URL(request.url).searchParams;
    const watchlist = getWatchlist(Number(params.watchlist_id));
    if (!watchlist) return notFound("watchlist not found");
    const insiderOrFundCiks = new Set(watchlist.items.filter((i) => i.kind !== "company").map((i) => i.cik));
    const companyCiks = new Set(watchlist.items.filter((i) => i.kind === "company").map((i) => i.cik));
    const rows = FEED.filter(
      (f) => f.owners.some((o) => insiderOrFundCiks.has(o.cik)) || (f.issuer !== null && companyCiks.has(f.issuer.cik)),
    );
    return HttpResponse.json(paginate(rows, sp));
  }),
  http.post("/api/watchlists/:watchlist_id/items", async ({ request, params }) => {
    const body = (await request.json()) as Schema<"WatchlistItemCreate">;
    const watchlist = addWatchlistItem(Number(params.watchlist_id), body.kind, body.cik);
    return watchlist ? HttpResponse.json(watchlist) : notFound("watchlist not found");
  }),
  http.delete("/api/watchlists/:watchlist_id/items/:kind/:cik", ({ params }) => {
    removeWatchlistItem(Number(params.watchlist_id), params.kind as Schema<"WatchlistItemCreate">["kind"], Number(params.cik));
    return new HttpResponse(null, { status: 204 });
  }),
];
