/**
 * Shared lightweight-charts plumbing. Charts draw on canvas, which can't resolve CSS custom
 * properties, so every chart reads the live theme tokens (set in index.css) at mount time and
 * again whenever `html.dark` toggles (AppShell flips that class; see F1).
 */
import { ColorType, type ChartOptions, type DeepPartial } from "lightweight-charts";

export interface ChartTheme {
  surface: string;
  grid: string;
  axis: string;
  text: string;
  pos: string;
  neg: string;
  /** --series-1 .. --series-8, in the fixed categorical order (never reassigned by rank). */
  series: string[];
  seriesOther: string;
  markerForm144: string;
  markerStake: string;
  markerCluster: string;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function readChartTheme(): ChartTheme {
  return {
    surface: cssVar("--chart-surface"),
    grid: cssVar("--chart-grid"),
    axis: cssVar("--chart-axis"),
    text: cssVar("--chart-text"),
    pos: cssVar("--pos"),
    neg: cssVar("--neg"),
    series: Array.from({ length: 8 }, (_, i) => cssVar(`--series-${i + 1}`)),
    seriesOther: cssVar("--series-other"),
    markerForm144: cssVar("--marker-form144"),
    markerStake: cssVar("--marker-stake"),
    markerCluster: cssVar("--marker-cluster"),
  };
}

/** Base chart options shared by every lightweight-charts instance in the app. */
export function baseChartOptions(theme: ChartTheme, width: number, height: number): DeepPartial<ChartOptions> {
  return {
    width,
    height,
    layout: { background: { type: ColorType.Solid, color: theme.surface }, textColor: theme.text, fontSize: 12 },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.axis },
    timeScale: { borderColor: theme.axis, borderVisible: true },
  };
}

/**
 * Keeps a chart sized to its container and re-themed when the page's light/dark mode
 * changes. Returns a cleanup function; call it from the mounting effect's own cleanup.
 */
export function watchChart(container: HTMLElement, onResize: (width: number) => void, onThemeChange: () => void): () => void {
  const resize = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width ?? container.clientWidth;
    if (width > 0) onResize(width);
  });
  resize.observe(container);
  const mutation = new MutationObserver(onThemeChange);
  mutation.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => {
    resize.disconnect();
    mutation.disconnect();
  };
}

/** `#rrggbb` -> `rgba(r,g,b,alpha)`, for area-chart fills. Passes through non-hex input. */
export function withAlpha(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = Number.parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
