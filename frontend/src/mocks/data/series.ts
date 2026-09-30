/**
 * Deterministic generators for mock time series: business days, OHLC bars, copycat
 * curves and the window statistics derived from them. Seeded, so every run (and every
 * test) sees the same numbers.
 */
import type { Schema } from "@/api/client";

type Bar = Schema<"Bar">;
type CurvePoint = Schema<"CurvePoint">;
type WindowStat = Schema<"WindowStat">;

/** mulberry32: a tiny seeded PRNG returning floats in [0, 1). */
export function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Standard normal draws (Box-Muller) from a uniform source. */
export function normal(u: () => number): () => number {
  return () => {
    const a = Math.max(u(), 1e-12);
    const b = u();
    return Math.sqrt(-2 * Math.log(a)) * Math.cos(2 * Math.PI * b);
  };
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Weekdays from start to end inclusive (ISO dates). Holidays are ignored in mocks. */
export function businessDays(start: string, end: string): string[] {
  const out: string[] = [];
  const d = new Date(`${start}T00:00:00Z`);
  const stop = new Date(`${end}T00:00:00Z`);
  while (d <= stop) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) out.push(iso(d));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

export function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return iso(d);
}

const round = (x: number, digits: number) => Number(x.toFixed(digits));

/** Daily bars whose last close is exactly `lastClose`. */
export function makeBars(
  start: string,
  end: string,
  lastClose: number,
  seed: number,
  dailyVol = 0.016,
): Bar[] {
  const days = businessDays(start, end);
  const u = rng(seed);
  const z = normal(u);
  const closes: number[] = [];
  let level = 1;
  for (let i = 0; i < days.length; i++) {
    level *= Math.exp(0.0002 + dailyVol * z());
    closes.push(level);
  }
  const scale = lastClose / closes[closes.length - 1];
  let prev = closes[0] * scale;
  return days.map((date, i) => {
    const close = closes[i] * scale;
    const open = prev * (1 + (u() - 0.5) * dailyVol);
    const high = Math.max(open, close) * (1 + u() * dailyVol * 0.6);
    const low = Math.min(open, close) * (1 - u() * dailyVol * 0.6);
    prev = close;
    const c = round(close, 2);
    return {
      date,
      open: round(open, 2),
      high: round(high, 2),
      low: round(low, 2),
      close: c,
      adj_close: c,
      volume: Math.round(200_000 + u() * 1_800_000),
    };
  });
}

interface Drift {
  nav: number;
  spy: number;
  qqq: number;
  sector: number;
}

/** A copycat curve (nav plus benchmarks), every series starting at 1.0. */
export function makeCurve(start: string, end: string, drift: Drift, seed: number): CurvePoint[] {
  const days = businessDays(start, end);
  const z = normal(rng(seed));
  const vol: Drift = { nav: 0.017, spy: 0.0105, qqq: 0.0135, sector: 0.0125 };
  const level: Drift = { nav: 1, spy: 1, qqq: 1, sector: 1 };
  return days.map((date, i) => {
    if (i > 0) {
      const market = z();
      for (const k of ["nav", "spy", "qqq", "sector"] as const) {
        const own = k === "spy" ? 0 : z();
        const beta = k === "spy" ? 1 : k === "nav" ? 0.9 : 1.1;
        level[k] *= 1 + drift[k] + vol[k] * (beta * market * 0.8 + own * 0.6);
      }
    }
    return {
      date,
      nav: round(level.nav, 4),
      spy: round(level.spy, 4),
      qqq: round(level.qqq, 4),
      sector: round(level.sector, 4),
    };
  });
}

const WINDOW_DAYS = { "1y": 252, "3y": 756, "5y": 1260 } as const;

function stdev(xs: number[]): number {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, xs.length - 1));
}

function statsOver(points: CurvePoint[], window: WindowStat["window"], invested: number): WindowStat {
  const empty: WindowStat = {
    window,
    ret: null,
    ret_spy: null,
    ret_qqq: null,
    ret_sector: null,
    annualized: null,
    vol: null,
    max_drawdown: null,
    beta: null,
    time_invested_pct: null,
  };
  if (points.length < 2) return empty;
  const [a, b] = [points[0], points[points.length - 1]];
  const navR = points.slice(1).map((p, i) => p.nav / points[i].nav - 1);
  const spyR = points.slice(1).map((p, i) => p.spy / points[i].spy - 1);
  const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length;
  const [mn, ms] = [mean(navR), mean(spyR)];
  const cov = navR.reduce((s, x, i) => s + (x - mn) * (spyR[i] - ms), 0) / (navR.length - 1);
  const varS = spyR.reduce((s, x) => s + (x - ms) ** 2, 0) / (spyR.length - 1);
  let peak = -Infinity;
  let maxDd = 0;
  for (const p of points) {
    peak = Math.max(peak, p.nav);
    maxDd = Math.min(maxDd, p.nav / peak - 1);
  }
  const ret = b.nav / a.nav - 1;
  const years = navR.length / 252;
  return {
    window,
    ret: round(ret, 4),
    ret_spy: round(b.spy / a.spy - 1, 4),
    ret_qqq: round(b.qqq / a.qqq - 1, 4),
    ret_sector: round(b.sector / a.sector - 1, 4),
    annualized: window === "3y" || window === "5y" ? round((1 + ret) ** (1 / years) - 1, 4) : null,
    vol: round(stdev(navR) * Math.sqrt(252), 4),
    max_drawdown: round(maxDd, 4),
    beta: varS > 0 ? round(cov / varS, 2) : null,
    time_invested_pct: invested,
  };
}

/**
 * Window stats in ytd, 1y, 3y, 5y order. YTD starts at the previous year's last close, or
 * at the first point when the curve starts later; longer windows need their full history.
 */
export function windowsFromCurve(points: CurvePoint[], invested = 0.82): WindowStat[] {
  if (points.length === 0) {
    return (["ytd", "1y", "3y", "5y"] as const).map((w) => statsOver([], w, invested));
  }
  const last = points[points.length - 1];
  const yearStart = `${last.date.slice(0, 4)}-01-01`;
  let ytdFrom = points.findIndex((p) => p.date >= yearStart);
  if (ytdFrom > 0) ytdFrom -= 1;
  const out: WindowStat[] = [statsOver(points.slice(Math.max(0, ytdFrom)), "ytd", invested)];
  for (const w of ["1y", "3y", "5y"] as const) {
    const n = WINDOW_DAYS[w];
    out.push(points.length > n ? statsOver(points.slice(-(n + 1)), w, invested) : statsOver([], w, invested));
  }
  return out;
}
