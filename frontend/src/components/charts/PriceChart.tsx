import { CandlestickSeries, createChart, createSeriesMarkers } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Schema } from "@/api/client";
import { baseChartOptions, readChartTheme, watchChart } from "./chartTheme";
import { toCandles, toMarkers } from "./mapping";

interface PriceChartProps {
  bars: Schema<"Bar">[];
  markers: Schema<"Marker">[];
  height?: number;
}

/** Daily candles with buy/sell/144/stake/cluster markers (spec 11, company and insider pages). */
export function PriceChart({ bars, markers, height = 320 }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const theme = readChartTheme();
    const chart = createChart(container, baseChartOptions(theme, container.clientWidth, height));
    const series = chart.addSeries(CandlestickSeries, {
      upColor: theme.pos,
      downColor: theme.neg,
      borderVisible: false,
      wickUpColor: theme.pos,
      wickDownColor: theme.neg,
    });
    series.setData(toCandles(bars));
    createSeriesMarkers(
      series,
      toMarkers(markers, {
        buy: theme.pos,
        sell: theme.neg,
        form144: theme.markerForm144,
        stake: theme.markerStake,
        cluster: theme.markerCluster,
      }),
    );
    chart.timeScale().fitContent();

    const stop = watchChart(
      container,
      (width) => chart.applyOptions({ width }),
      () => {
        const t = readChartTheme();
        chart.applyOptions(baseChartOptions(t, container.clientWidth, height));
        series.applyOptions({ upColor: t.pos, downColor: t.neg, wickUpColor: t.pos, wickDownColor: t.neg });
      },
    );
    return () => {
      stop();
      chart.remove();
    };
  }, [bars, markers, height]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
