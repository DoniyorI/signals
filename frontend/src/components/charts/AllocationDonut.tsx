import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, type TooltipContentProps } from "recharts";
import type { Schema } from "@/api/client";
import { fmtPct, fmtUsd } from "@/lib/format";
import { topSlices } from "./mapping";

type AllocationSlice = Schema<"AllocationSlice">;

const TOKENS = Array.from({ length: 8 }, (_, i) => `--series-${i + 1}`);
const OTHER_TOKEN = "--series-other";

function tokenFor(slice: AllocationSlice, index: number): string {
  return slice.key === "other" ? OTHER_TOKEN : (TOKENS[index] ?? OTHER_TOKEN);
}

function DonutTooltip({ active, payload }: TooltipContentProps) {
  const slice = payload?.[0]?.payload as AllocationSlice | undefined;
  if (!active || !slice) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md">
      <div className="font-medium">{slice.label}</div>
      <div className="text-muted-foreground">
        {fmtUsd(slice.value_usd)} · {fmtPct(slice.weight, { signed: false })}
      </div>
    </div>
  );
}

interface AllocationDonutProps {
  slices: AllocationSlice[];
  height?: number;
}

/** A by-sector or by-issuer allocation donut, folding anything past the top 8 into "Other". */
export function AllocationDonut({ slices, height = 220 }: AllocationDonutProps) {
  const data = topSlices(slices, 8);
  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No holdings to show.</p>;
  }
  return (
    <div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value_usd"
              nameKey="label"
              innerRadius="55%"
              outerRadius="90%"
              paddingAngle={1}
              stroke="var(--card)"
              strokeWidth={2}
            >
              {data.map((slice, i) => (
                <Cell key={slice.key} fill={`var(${tokenFor(slice, i)})`} />
              ))}
            </Pie>
            <Tooltip content={DonutTooltip} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {data.map((slice, i) => (
          <li key={slice.key} className="flex items-center gap-1.5 truncate">
            <span
              className="inline-block size-2 shrink-0 rounded-full"
              style={{ background: `var(${tokenFor(slice, i)})` }}
              aria-hidden
            />
            <span className="truncate">{slice.label}</span>
            <span className="ml-auto tabular-nums">{fmtPct(slice.weight, { signed: false })}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
