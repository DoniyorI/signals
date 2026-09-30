import type { Schema } from "@/api/client";
import { cn } from "@/lib/utils";

type Change = Schema<"FundHoldingRow">["change"];

const CHANGE_META: Record<Change, { label: string; cls: string }> = {
  NEW: { label: "New", cls: "bg-pos-soft text-pos" },
  ADD: { label: "Add", cls: "bg-pos-soft text-pos" },
  TRIM: { label: "Trim", cls: "bg-warn-soft text-warn" },
  EXIT: { label: "Exit", cls: "bg-neg-soft text-neg" },
  SAME: { label: "Same", cls: "bg-muted text-muted-foreground" },
};

/** A 13F position-change chip: NEW, ADD, TRIM, EXIT or SAME. */
export function ChangeChip({ change }: { change: Change }) {
  const meta = CHANGE_META[change];
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", meta.cls)}>
      {meta.label}
    </span>
  );
}
