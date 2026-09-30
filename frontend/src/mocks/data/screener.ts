/** `/api/screener/insiders` and `/api/screener/funds`: filter, sort and shape the rosters. */
import type { Schema } from "@/api/client";
import { fundHeader, fundPerformance, fundStats } from "./funds";
import { insiderDecisions, insiderHeader, insiderPerformance, insiderProfile, INSIDER_CIKS } from "./insiders";
import { FUNDS, issuerInfo } from "./world";

type InsiderScreenRow = Schema<"InsiderScreenRow">;
type FundScreenRow = Schema<"FundScreenRow">;
type Basis = "filed" | "executed";
type WindowStat = Schema<"WindowStat">;

const WINDOW_NAMES = ["ytd", "1y", "3y", "5y"] as const;

function windowMap(windows: WindowStat[]): Record<string, number | null> {
  const byName = new Map(windows.map((w) => [w.window, w.ret]));
  return Object.fromEntries(WINDOW_NAMES.map((w) => [w, byName.get(w) ?? null]));
}

function primaryIssuer(cik: number, basis: Basis, include: boolean) {
  const decisions = insiderDecisions(cik, basis, include, null);
  if (!decisions.length) return null;
  const counts = new Map<number, { issuer: (typeof decisions)[number]["issuer"]; n: number }>();
  for (const d of decisions) {
    const entry = counts.get(d.issuer.cik) ?? { issuer: d.issuer, n: 0 };
    entry.n += 1;
    counts.set(d.issuer.cik, entry);
  }
  return [...counts.values()].sort((a, b) => b.n - a.n)[0].issuer;
}

function insiderRow(cik: number, basis: Basis, include: boolean): InsiderScreenRow {
  const header = insiderHeader(cik, basis, include)!;
  const profile = insiderProfile(cik)!;
  const decisions = insiderDecisions(cik, basis, include, null);
  const lastTrade = decisions.map((d) => d.first_trade_date).sort().at(-1) ?? null;
  const issuer = primaryIssuer(cik, basis, include);
  return {
    owner: profile.owner,
    primary_issuer: issuer,
    roles: profile.roles[0]?.roles ?? [],
    sector: issuer ? (issuerInfo(issuer.cik)?.sector ?? null) : null,
    rating: header.rating,
    avg_roi_6m: header.avg_roi_6m,
    hit_rate: header.hit_rate,
    risk_label: header.risk_label,
    n_decisions: header.n_decisions,
    last_trade_date: lastTrade,
    windows: windowMap(insiderPerformance(cik, basis, include).windows),
  };
}

function fundRow(cik: number, basis: Basis): FundScreenRow {
  const header = fundHeader(cik)!;
  const stats = fundStats(cik);
  const perf = fundPerformance(cik, basis);
  return {
    fund: { cik, name: header.name },
    rating: header.rating,
    coverage_pct: header.coverage_pct,
    latest_value_usd: header.latest_value_usd,
    positions: header.latest_positions,
    risk_label: stats?.risk ?? null,
    top_sector: null, // holdings-derived; not needed until F8/F9 build the sector column
    windows: windowMap(perf?.windows ?? []),
  };
}

interface CommonFilters {
  sectors: string[];
  minRating: number | null;
  confidence: string[];
  window: (typeof WINDOW_NAMES)[number];
  minReturn: number | null;
  maxReturn: number | null;
  risk: string[];
  basis: Basis;
  sort: string | null;
  order: string;
}

function readCommon(sp: URLSearchParams): CommonFilters {
  return {
    sectors: sp.getAll("sectors").filter(Boolean),
    minRating: sp.get("min_rating") ? Number(sp.get("min_rating")) : null,
    confidence: sp.getAll("confidence").filter(Boolean),
    window: (sp.get("window") as (typeof WINDOW_NAMES)[number] | null) ?? "1y",
    minReturn: sp.get("min_return") ? Number(sp.get("min_return")) : null,
    maxReturn: sp.get("max_return") ? Number(sp.get("max_return")) : null,
    risk: sp.getAll("risk").filter(Boolean),
    basis: (sp.get("basis") as Basis | null) ?? "filed",
    sort: sp.get("sort"),
    order: sp.get("order") ?? "desc",
  };
}

function passesCommon(
  f: CommonFilters,
  row: { rating: Schema<"Rating">; risk_label: string | null; windows: Record<string, number | null> },
): boolean {
  if (f.minRating !== null && (row.rating.score ?? -Infinity) < f.minRating) return false;
  if (f.confidence.length && (!row.rating.confidence || !f.confidence.includes(row.rating.confidence))) return false;
  if (f.risk.length && (!row.risk_label || !f.risk.includes(row.risk_label))) return false;
  const ret = row.windows[f.window];
  if (f.minReturn !== null && (ret ?? -Infinity) < f.minReturn) return false;
  if (f.maxReturn !== null && (ret ?? Infinity) > f.maxReturn) return false;
  return true;
}

function sortRows<T>(
  rows: T[],
  sort: string | null,
  order: string,
  accessors: Record<string, (r: T) => number | null>,
): T[] {
  const accessor = sort ? accessors[sort] : undefined;
  if (!accessor) return rows;
  const dir = order === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const [av, bv] = [accessor(a), accessor(b)];
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return (av - bv) * dir;
  });
}

export function screenInsiders(sp: URLSearchParams): InsiderScreenRow[] {
  const common = readCommon(sp);
  const roles = sp.getAll("roles").filter(Boolean);
  const sectors = common.sectors;
  const minDecisions = sp.get("min_decisions") ? Number(sp.get("min_decisions")) : 0;
  const lastTradeFrom = sp.get("last_trade_from");
  const lastTradeTo = sp.get("last_trade_to");
  const include = sp.get("include_10b5_1") !== "false";
  const rows = INSIDER_CIKS.map((cik) => insiderRow(cik, common.basis, include)).filter((row) => {
    if (!passesCommon(common, row)) return false;
    if (roles.length && !row.roles.some((r) => roles.includes(r))) return false;
    if (sectors.length && (!row.sector || !sectors.includes(row.sector))) return false;
    if (row.n_decisions < minDecisions) return false;
    if (lastTradeFrom && (!row.last_trade_date || row.last_trade_date < lastTradeFrom)) return false;
    if (lastTradeTo && (!row.last_trade_date || row.last_trade_date > lastTradeTo)) return false;
    return true;
  });
  return sortRows(rows, common.sort, common.order, {
    avg_roi_6m: (r) => r.avg_roi_6m,
    hit_rate: (r) => r.hit_rate,
    rating: (r) => r.rating.score,
    n_decisions: (r) => r.n_decisions,
  });
}

export function screenFunds(sp: URLSearchParams): FundScreenRow[] {
  const common = readCommon(sp);
  const trackedOnly = sp.get("tracked_only") === "true";
  const rows = FUNDS.map((f) => fundRow(f.cik, common.basis)).filter((row) => {
    if (!passesCommon(common, row)) return false;
    if (trackedOnly && row.coverage_pct === null) return false;
    return true;
  });
  return sortRows(rows, common.sort, common.order, {
    rating: (r) => r.rating.score,
    latest_value_usd: (r) => r.latest_value_usd,
    positions: (r) => r.positions,
  });
}
