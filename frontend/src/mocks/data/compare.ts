/** `/api/compare`: up to 4 insider/fund profiles side by side, overlaid on one nav curve. */
import type { Schema } from "@/api/client";
import { fundHeader, fundHoldings, fundPerformance, fundStats } from "./funds";
import { insiderHeader, insiderHoldings, insiderPerformance } from "./insiders";

type CompareOut = Schema<"CompareOut">;
type CompareProfile = Schema<"CompareProfile">;
type Basis = "filed" | "executed";

function profileFor(id: string, basis: Basis, include: boolean): CompareProfile | undefined {
  const [kind, cikStr] = id.split(":");
  const cik = Number(cikStr);
  if (kind === "insider") {
    const header = insiderHeader(cik, basis, include);
    if (!header) return undefined;
    const perf = insiderPerformance(cik, basis, include);
    return {
      id,
      kind: "insider",
      name: header.name,
      rating: header.rating,
      avg_roi_6m: header.avg_roi_6m,
      hit_rate: header.hit_rate,
      curve: perf.points,
      windows: perf.windows,
      by_sector: insiderHoldings(cik).by_sector,
    };
  }
  if (kind === "fund") {
    const header = fundHeader(cik);
    if (!header) return undefined;
    const perf = fundPerformance(cik, basis);
    const stats = fundStats(cik);
    return {
      id,
      kind: "fund",
      name: header.name,
      rating: header.rating,
      avg_roi_6m: stats?.avgRoi6m ?? null,
      hit_rate: stats?.hitRate ?? null,
      curve: perf?.points ?? [],
      windows: perf?.windows ?? [],
      by_sector: fundHoldings(cik, null)?.by_sector ?? [],
    };
  }
  return undefined;
}

export function compare(ids: string, basis: Basis, include: boolean): CompareOut {
  const profiles = ids
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean)
    .slice(0, 4)
    .map((id) => profileFor(id, basis, include))
    .filter((p): p is CompareProfile => p !== undefined);
  return { basis, profiles };
}
