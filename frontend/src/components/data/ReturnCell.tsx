import { fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A signed, colored return figure. Uses the Tailwind 4 theme utilities `text-pos`/`text-neg`
 * (backed by `--pos`/`--neg` via `@theme inline`) rather than `text-[--pos]` — Tailwind 4
 * changed CSS-var shorthand to `(--x)`, so the literal plan class would emit invalid CSS and
 * render uncolored (ledger Ruling P1).
 */
export function ReturnCell({ value, digits }: { value: number | null | undefined; digits?: number }) {
  const cls =
    value === null || value === undefined
      ? "text-muted-foreground"
      : value > 0
        ? "text-pos"
        : value < 0
          ? "text-neg"
          : "text-foreground";
  return <span className={cn("tabular-nums", cls)}>{fmtPct(value, { digits })}</span>;
}
