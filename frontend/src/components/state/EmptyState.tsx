import type { ReactNode } from "react";
import { NOT_ENOUGH_DATA } from "@/lib/format";

export type EmptyReason = "loading" | "insufficient" | "not_covered" | "error";

/** A muted placeholder for a table/section with nothing to show (no results, no data yet). */
export function EmptyState({
  title,
  description,
  action,
  reason,
  percent,
  completedTrades,
}: {
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  reason?: EmptyReason;
  /** Percentage points (37 means 37%); API coverage fractions are converted by the caller. */
  percent?: number | null;
  completedTrades?: number | null;
}) {
  const titles: Record<EmptyReason, string> = {
    loading: "Performance is loading",
    insufficient: NOT_ENOUGH_DATA,
    not_covered: "No price data for this security.",
    error: "Data didn't load",
  };
  const explanations: Partial<Record<EmptyReason, string>> = {
    loading: `Performance appears when prices finish loading${percent != null ? ` (${Math.round(percent)}% done)` : ""}.`,
    insufficient: `Needs 3+ completed trades${completedTrades != null ? ` (has ${completedTrades})` : ""}.`,
    error: "Try again to load the data.",
  };
  const explanation = description ?? (reason ? explanations[reason] : undefined);
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-center">
      <p className="text-sm font-medium text-foreground">{title ?? (reason ? titles[reason] : undefined)}</p>
      {explanation && <p className="max-w-sm text-sm text-muted-foreground">{explanation}</p>}
      {action}
    </div>
  );
}
