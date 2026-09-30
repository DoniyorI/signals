import { AreaSeries, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Schema } from "@/api/client";
import { baseChartOptions, readChartTheme, watchChart, withAlpha } from "./chartTheme";

interface ValueChartProps {
  points: Schema<"FundValuePoint">[];
  height?: number;
}

function areaData(points: Schema<"FundValuePoint">[]) {
  return [...points]
    .sort((a, b) => a.period.localeCompare(b.period))
    .map((p) => ({ time: p.period, value: p.value_usd }));
}

/** A fund's reported 13F value over time (spec 11, fund page header). */
export function ValueChart({ points, height = 160 }: ValueChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const theme = readChartTheme();
    const chart = createChart(container, baseChartOptions(theme, container.clientWidth, height));
    const series = chart.addSeries(AreaSeries, {
      lineColor: theme.series[0],
      topColor: withAlpha(theme.series[0], 0.35),
      bottomColor: withAlpha(theme.series[0], 0),
      lineWidth: 2,
    });
    series.setData(areaData(points));
    chart.timeScale().fitContent();

    const stop = watchChart(
      container,
      (width) => chart.applyOptions({ width }),
      () => {
        const t = readChartTheme();
        chart.applyOptions(baseChartOptions(t, container.clientWidth, height));
        series.applyOptions({
          lineColor: t.series[0],
          topColor: withAlpha(t.series[0], 0.35),
          bottomColor: withAlpha(t.series[0], 0),
        });
      },
    );
    return () => {
      stop();
      chart.remove();
    };
  }, [points, height]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
