import { Badge } from "@/components/ui/badge";
import { PLAN_LABELS } from "@/lib/badges";

/** A 10b5-1 plan chip; renders nothing for "none" (the common case shouldn't add noise). */
export function PlanChip({ flag }: { flag: "flag" | "footnote" | "none" | null | undefined }) {
  const label = flag ? PLAN_LABELS[flag] : null;
  if (!label) return null;
  return (
    <Badge variant="outline" className="font-normal text-muted-foreground">
      {label}
    </Badge>
  );
}
