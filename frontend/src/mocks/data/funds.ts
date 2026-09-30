/**
 * 13F funds. Example Capital Management (3000001) is tracked with periods 2024-03-31 and
 * 2024-06-30: it holds ACME (000000AA1) and GLBX (000000BB2) and exits 000000CC3.
 * Small Fry Advisors (3999999) is untracked, so its performance endpoint is a 404.
 */
import type { Schema } from "@/api/client";
import { makeCurve, windowsFromCurve } from "./series";
import { AS_OF, EXAMPLE_CAPITAL, QUIET_HARBOR } from "./world";

type FundHoldingRow = Schema<"FundHoldingRow">;
type SecurityRef = Schema<"SecurityRef">;

const SEC_ACME: SecurityRef = { cusip: "000000AA1", name: "Acme Corp", ticker: "ACME", issuer_cik: 1000001 };
const SEC_GLBX: SecurityRef = { cusip: "000000BB2", name: "Globex Inc", ticker: "GLBX", issuer_cik: 1000002 };
const SEC_OLD: SecurityRef = { cusip: "000000CC3", name: "Old Co", ticker: "XYZA", issuer_cik: 1000003 };

function row(
  security: SecurityRef,
  sector: string,
  change: FundHoldingRow["change"],
  shares: number,
  value: number,
  weight: number | null,
  prevWeight: number | null,
  sharesChangePct: number | null,
  highConviction: boolean,
): FundHoldingRow {
  return {
    security,
    put_call: null,
    shares,
    value_usd: value,
    weight,
    prev_weight: prevWeight,
    change,
    shares_change_pct: sharesChangePct,
    sector,
    high_conviction: highConviction,
  };
}

interface PeriodHoldings {
  rows: FundHoldingRow[];
  exits: FundHoldingRow[];
}

export const FUND_HOLDINGS: Record<number, Record<string, PeriodHoldings>> = {
  [EXAMPLE_CAPITAL.cik]: {
    "2024-03-31": {
      rows: [
        row(SEC_ACME, "Technology", "NEW", 2_500_000, 22_900_000, 0.5995, null, null, true),
        row(SEC_OLD, "Industrials", "NEW", 654_000, 15_300_000, 0.4005, null, null, true),
      ],
      exits: [],
    },
    "2024-06-30": {
      rows: [
        row(SEC_ACME, "Technology", "ADD", 3_100_000, 31_000_000, 0.62, 0.5995, 0.24, true),
        row(SEC_GLBX, "Communication Services", "NEW", 447_059, 19_000_000, 0.38, null, null, true),
      ],
      exits: [row(SEC_OLD, "Industrials", "EXIT", 0, 0, null, 0.4005, -1, false)],
    },
  },
  [QUIET_HARBOR.cik]: {
    "2024-03-31": {
      rows: [row(SEC_OLD, "Industrials", "NEW", 132_000, 3_100_000, 1, null, null, true)],
      exits: [],
    },
    "2024-06-30": {
      rows: [row(SEC_ACME, "Technology", "NEW", 400_000, 4_000_000, 1, null, null, true)],
      exits: [row(SEC_OLD, "Industrials", "EXIT", 0, 0, null, 1, -1, false)],
    },
  },
};

const r4 = (x: number) => Math.round(x * 10_000) / 10_000;

export function fundPeriods(cik: number): string[] {
  return Object.keys(FUND_HOLDINGS[cik] ?? {}).sort().reverse();
}

export function fundHoldings(cik: number, period: string | null): Schema<"FundHoldingsOut"> | undefined {
  const periods = fundPeriods(cik);
  const chosen = period ?? periods[0];
  const h = FUND_HOLDINGS[cik]?.[chosen];
  if (!h) return undefined;
  const bySector = new Map<string, number>();
  for (const r of h.rows) bySector.set(r.sector ?? "Unknown", (bySector.get(r.sector ?? "Unknown") ?? 0) + r.value_usd);
  const total = h.rows.reduce((s, r) => s + r.value_usd, 0);
  const weights = h.rows.map((r) => r.value_usd / total);
  return {
    period: chosen,
    periods_available: periods,
    rows: [...h.rows].sort((a, b) => b.value_usd - a.value_usd),
    exits: h.exits,
    by_sector: [...bySector.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ key: label, label, value_usd: value, weight: r4(value / total) })),
    effective_n: r4(1 / weights.reduce((s, w) => s + w * w, 0)),
    top5_weight: r4([...weights].sort((a, b) => b - a).slice(0, 5).reduce((s, w) => s + w, 0)),
    next_cursor: null,
  };
}

export const TRACKED_FUNDS = [EXAMPLE_CAPITAL.cik];

/**
 * Rating and headline stats come from `profile_stats`, which (per the backend seed world)
 * exists for every fund manager regardless of tracking — only the nav *curve* is gated on
 * `is_tracked`. Small Fry (untracked) still has a real, low rating so the screener's
 * "tracked only" filter has something genuine to exclude, matching the backend's own ruling.
 */
const FUND_RATINGS: Record<
  number,
  { score: number; confidence: "low" | "medium" | "high"; risk: "low" | "medium" | "high"; avgRoi6m: number; hitRate: number }
> = {
  [EXAMPLE_CAPITAL.cik]: { score: 71, confidence: "low", risk: "medium", avgRoi6m: 0.03, hitRate: 0.75 },
  [QUIET_HARBOR.cik]: { score: 20, confidence: "low", risk: "low", avgRoi6m: 0.01, hitRate: 0.5 },
};

export function fundRating(cik: number): Schema<"Rating"> {
  const r = FUND_RATINGS[cik];
  return r ? { score: r.score, confidence: r.confidence, n: 1 } : { score: null, confidence: null, n: 0 };
}

export function fundStats(cik: number) {
  return FUND_RATINGS[cik];
}

export function fundPerformance(cik: number, basis: "filed" | "executed"): Schema<"PerformanceOut"> | undefined {
  if (!TRACKED_FUNDS.includes(cik)) return undefined;
  const points = makeCurve(
    "2024-04-01",
    AS_OF,
    { nav: basis === "filed" ? 0.0009 : 0.00105, spy: 0.0006, qqq: 0.0007, sector: 0.00065 },
    basis === "filed" ? 91 : 92,
  );
  return { basis, points, windows: windowsFromCurve(points, 1), coverage_pct: 0.92, as_of: AS_OF };
}

export function fundHeader(cik: number): Schema<"FundHeader"> | undefined {
  const fund = [EXAMPLE_CAPITAL, QUIET_HARBOR].find((f) => f.cik === cik);
  if (!fund) return undefined;
  const periods = fundPeriods(cik).reverse();
  const history = periods.map((p) => {
    const h = FUND_HOLDINGS[cik][p];
    return { period: p, value_usd: h.rows.reduce((s, r) => s + r.value_usd, 0), positions: h.rows.length };
  });
  const latest = history[history.length - 1];
  const tracked = TRACKED_FUNDS.includes(cik);
  return {
    cik,
    name: fund.name,
    is_tracked: tracked,
    latest_period: latest?.period ?? null,
    latest_value_usd: latest?.value_usd ?? null,
    latest_positions: latest?.positions ?? null,
    value_history: history,
    rating: fundRating(cik),
    windows: tracked ? fundPerformance(cik, "filed")!.windows : [],
    coverage_pct: tracked ? 0.92 : null,
    insider_cik: null,
  };
}
