/**
 * Pure data mappers from API shapes to lightweight-charts / Recharts inputs. Kept dependency-
 * free of any rendering so they're trivial to unit test (plan 07 Task F3, step 1).
 */
import type { CandlestickData, SeriesMarker, Time } from "lightweight-charts";
import type { Schema } from "@/api/client";

type Bar = Schema<"Bar">;
type Marker = Schema<"Marker">;
type CurvePoint = Schema<"CurvePoint">;
type AllocationSlice = Schema<"AllocationSlice">;

/** OHLC candles, sorted ascending by date (lightweight-charts requires ascending time). */
export function toCandles(bars: Bar[]): CandlestickData[] {
  return [...bars]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close }));
}

/**
 * Concrete colors for each marker kind. Canvas-drawn charts can't resolve CSS custom
 * properties, so callers read the live theme tokens (`--pos`, `--neg`, `--marker-*`) and pass
 * them in; the defaults here are the light-theme values, for callers (and tests) that don't
 * need theme-awareness.
 */
export interface MarkerPalette {
  buy: string;
  sell: string;
  form144: string;
  stake: string;
  cluster: string;
}

export const DEFAULT_MARKER_PALETTE: MarkerPalette = {
  buy: "#0a7a43",
  sell: "#c42b2b",
  form144: "#eda100",
  stake: "#2a78d6",
  cluster: "#4a3aa7",
};

const MARKER_SPEC: Record<
  Marker["kind"],
  { shape: "circle" | "square" | "arrowUp" | "arrowDown"; position: "aboveBar" | "belowBar"; text: string }
> = {
  buy: { shape: "arrowUp", position: "belowBar", text: "B" },
  sell: { shape: "arrowDown", position: "aboveBar", text: "S" },
  form144: { shape: "circle", position: "aboveBar", text: "144" },
  stake: { shape: "square", position: "belowBar", text: "13D" },
  cluster: { shape: "circle", position: "belowBar", text: "C" },
};

/** Price-chart markers, sorted ascending by time (lightweight-charts requires this order). */
export function toMarkers(markers: Marker[], palette: MarkerPalette = DEFAULT_MARKER_PALETTE): SeriesMarker<Time>[] {
  return markers
    .map((m) => {
      const spec = MARKER_SPEC[m.kind];
      return {
        time: m.date,
        position: spec.position,
        shape: spec.shape,
        color: palette[m.kind],
        text: spec.text,
        id: m.ref,
      };
    })
    .sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

type CurveKey = Exclude<keyof CurvePoint, "date">;

/** One `{time,value}` line per requested key (nav/spy/qqq/sector), ascending by date. */
export function toLines<K extends CurveKey>(
  points: CurvePoint[],
  keys: readonly K[],
): Record<K, { time: Time; value: number }[]> {
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  return Object.fromEntries(keys.map((key) => [key, sorted.map((p) => ({ time: p.date, value: p[key] }))])) as Record<
    K,
    { time: Time; value: number }[]
  >;
}

/** Keeps the top `n` slices by value; the remainder collapses into one "Other" slice. */
export function topSlices(slices: AllocationSlice[], n = 8): AllocationSlice[] {
  const sorted = [...slices].sort((a, b) => b.value_usd - a.value_usd);
  if (sorted.length <= n) return sorted;
  const rest = sorted.slice(n);
  const other: AllocationSlice = {
    key: "other",
    label: "Other",
    value_usd: rest.reduce((sum, s) => sum + s.value_usd, 0),
    weight: rest.reduce((sum, s) => sum + s.weight, 0),
  };
  return [...sorted.slice(0, n), other];
}
