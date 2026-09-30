import type { Schema } from "@/api/client";
import { ratingLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

const CONFIDENCE_TONE: Record<"low" | "medium" | "high", string> = {
  high: "bg-pos-soft text-pos",
  medium: "bg-warn-soft text-warn",
  low: "bg-muted text-muted-foreground",
};

/** "78 · High", or "Not enough data yet" when the profile has no complete decisions. */
export function RatingPill({ rating }: { rating: Schema<"Rating"> }) {
  const tone = rating.confidence ? CONFIDENCE_TONE[rating.confidence] : "bg-muted text-muted-foreground";
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium tabular-nums", tone)}>
      {ratingLabel(rating.score, rating.confidence)}
    </span>
  );
}
