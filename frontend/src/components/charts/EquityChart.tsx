import { LineSeries, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Schema } from "@/api/client";
import { baseChartOptions, readChartTheme, watchChart } from "./chartTheme";
import { toLines } from "./mapping";

type CurveKey = "nav" | "spy" | "qqq" | "sector";

/** Fixed categorical assignment (spec/dataviz rule: color follows the entity, never rank). */
const SERIES_META: Record<CurveKey, { label: string; token: string }> = {
  nav: { label: "This portfolio", token: "--series-1" },
  spy: { label: "S&P 500", token: "--series-2" },
  qqq: { label: "Nasdaq 100", token: "--series-3" },
  sector: { label: "Sector", token: "--series-4" },
};
const ORDER: CurveKey[] = ["nav", "spy", "qqq", "sector"];

interface EquityChartProps {
  points: Schema<"CurvePoint">[];
  /** Which series to draw; omitted or not `false` means visible. Defaults to all four. */
  show?: Partial<Record<CurveKey, boolean>>;
  height?: number;
}

/** An indexed nav-vs-benchmarks line chart. Always paired with a WindowsTable (the "table
 * twin" the dataviz review calls for on a >2-series light-mode legend). */
export function EquityChart({ points, show, height = 240 }: EquityChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const keys = ORDER.filter((k) => show?.[k] !== false);
  const keysSignature = keys.join(",");

  useEffect(() => {
    const container = containerRef.current;
    if (!container || keys.length === 0) return undefined;
    const theme = readChartTheme();
    const chart = createChart(container, baseChartOptions(theme, container.clientWidth, height));
    const lines = toLines(points, keys);
    const series = keys.map((key) => {
      const s = chart.addSeries(LineSeries, { color: cssColor(theme, key), lineWidth: 2 });
      s.setData(lines[key]);
      return s;
    });
    chart.timeScale().fitContent();

    const stop = watchChart(
      container,
      (width) => chart.applyOptions({ width }),
      () => {
        const t = readChartTheme();
        chart.applyOptions(baseChartOptions(t, container.clientWidth, height));
        series.forEach((s, i) => s.applyOptions({ color: cssColor(t, keys[i]) }));
      },
    );
    return () => {
      stop();
      chart.remove();
    };
    // `keysSignature` stands in for `keys` (a fresh array every render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, keysSignature, height]);

  return (
    <div>
      <div ref={containerRef} className="w-full" style={{ height }} />
      {keys.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {keys.map((key) => (
            <span key={key} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block size-2 rounded-full"
                style={{ background: `var(${SERIES_META[key].token})` }}
                aria-hidden
              />
              {SERIES_META[key].label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function cssColor(theme: ReturnType<typeof readChartTheme>, key: CurveKey): string {
  const index = ORDER.indexOf(key);
  return theme.series[index] ?? theme.seriesOther;
}
