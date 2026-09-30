import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtDate } from "@/lib/format";

/** Reads/writes `?period=` over a fund's or company's available 13F quarters (newest first). */
export function QuarterSelect({ periods }: { periods: string[] }) {
  const latest = periods[0] ?? null;
  const [period, setPeriod] = useUrlState<string | null>(
    "period",
    latest,
    (raw) => raw,
    (v) => v,
  );
  const value = period ?? latest ?? "";
  if (periods.length === 0) return null;
  return (
    <Select value={value} onValueChange={setPeriod}>
      <SelectTrigger size="sm" aria-label="Quarter">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {periods.map((p) => (
          <SelectItem key={p} value={p}>
            {fmtDate(p)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
