import type { Schema } from "@/api/client";
import type { ReactNode } from "react";
import { useId } from "react";
import { ratingLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

const CONFIDENCE_TONE: Record<"low" | "medium" | "high", string> = {
  high: "bg-pos-soft text-pos",
  medium: "bg-warn-soft text-warn",
  low: "bg-muted text-muted-foreground",
};

/** "78 · High", or "Not enough data yet" when the profile has no complete decisions. */
export function RatingPill({ rating, description, compact = false }: { rating: Schema<"Rating">; description?: ReactNode; compact?: boolean }) {
  const descriptionId = useId();
  const explanation = description ?? "Rating appears after completed six-month returns are calculated.";
  const tone = rating.confidence ? CONFIDENCE_TONE[rating.confidence] : "bg-muted text-muted-foreground";
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium tabular-nums", tone)}
        aria-describedby={rating.score === null ? descriptionId : undefined}
        title={rating.score === null && compact && typeof explanation === "string" ? explanation : undefined}>
        {ratingLabel(rating.score, rating.confidence)}
      </span>
      {rating.score === null && <span id={descriptionId} className={compact ? "sr-only" : "max-w-xs text-xs font-normal text-muted-foreground"}>
        {explanation}
      </span>}
    </span>
  );
}
