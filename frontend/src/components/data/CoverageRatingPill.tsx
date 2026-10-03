import type { Schema } from "@/api/client";
import { useCoverage } from "@/hooks/useCoverage";
import { usePriceLoadStatus } from "@/hooks/usePriceLoadStatus";
import { RatingPill } from "./RatingPill";

/** The global loading status gives context without inventing a per-entity mapping diagnosis.
 * Tables use an accessible description and native tooltip to preserve compact row height. */
export function CoverageRatingPill({ rating, quarterly = false, compact = false }: {
  rating: Schema<"Rating">;
  quarterly?: boolean;
  compact?: boolean;
}) {
  const coverage = useCoverage(rating.score === null);
  const priceStatus = usePriceLoadStatus(rating.score === null && coverage.isSuccess);
  let description = quarterly ? "Rating appears after completed quarterly returns are calculated." :
    "Rating appears after completed six-month returns are calculated.";
  if (coverage.isError) description = "Coverage details didn't load. Check Data health or try again.";
  else if (priceStatus.state === "failed") description = "Price loading needs attention. Check Data health for details.";
  else if (coverage.data?.prices.loading) {
    const pct = coverage.data.prices.pct;
    description = priceStatus.state === "queued" ?
      `Price loading is queued${pct == null ? "" : ` (${Math.round(pct * 100)}% covered)`}. Rating appears after returns are calculated.` :
      `${pct == null ? "Price work is queued or running" : `Prices ${Math.round(pct * 100)}% loaded`}. Rating appears after returns are calculated.`;
  }
  return <RatingPill rating={rating} description={description} compact={compact} />;
}
