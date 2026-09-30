import type { Schema } from "@/api/client";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fmtPct } from "@/lib/format";
import { ReturnCell } from "./ReturnCell";

type WindowStat = Schema<"WindowStat">;

const ROWS: { key: WindowStat["window"]; label: string }[] = [
  { key: "ytd", label: "YTD" },
  { key: "1y", label: "1Y" },
  { key: "3y", label: "3Y" },
  { key: "5y", label: "5Y" },
];

/** `ret` minus the benchmark's own return; null if either side is missing. */
function vs(ret: number | null | undefined, benchmark: number | null | undefined): number | null {
  return ret == null || benchmark == null ? null : ret - benchmark;
}

/** Rows YTD/1Y/3Y/5Y; columns Return, vs SPY, vs QQQ, vs Sector, Vol, Max DD. */
export function WindowsTable({ windows }: { windows: WindowStat[] }) {
  const byWindow = new Map(windows.map((w) => [w.window, w]));
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Window</TableHead>
          <TableHead className="text-right">Return</TableHead>
          <TableHead className="text-right">vs SPY</TableHead>
          <TableHead className="text-right">vs QQQ</TableHead>
          <TableHead className="text-right">vs Sector</TableHead>
          <TableHead className="text-right">Vol</TableHead>
          <TableHead className="text-right">Max DD</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {ROWS.map(({ key, label }) => {
          const w = byWindow.get(key);
          return (
            <TableRow key={key}>
              <TableCell className="font-medium">{label}</TableCell>
              <TableCell className="text-right">
                <ReturnCell value={w?.ret} />
              </TableCell>
              <TableCell className="text-right">
                <ReturnCell value={vs(w?.ret, w?.ret_spy)} />
              </TableCell>
              <TableCell className="text-right">
                <ReturnCell value={vs(w?.ret, w?.ret_qqq)} />
              </TableCell>
              <TableCell className="text-right">
                <ReturnCell value={vs(w?.ret, w?.ret_sector)} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmtPct(w?.vol, { signed: false })}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtPct(w?.max_drawdown, { signed: false })}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
