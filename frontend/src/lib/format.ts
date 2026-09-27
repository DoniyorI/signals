/**
 * Display formatters. The API sends percentages as fractions (0.123 = 12.3%), money as
 * USD floats and dates as ISO strings; everything here turns those into table-ready text.
 * Missing values render as an em dash so empty cells never read as zero.
 */

export const DASH = "—";

const ET = "America/New_York";

const usdFull = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const shares = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const dateUtc = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});
const dateEt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: ET,
});
const timeEt = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: ET,
});

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function isNum(n: number | null | undefined): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** ICU puts narrow no-break spaces before AM/PM; tables and tests want plain spaces. */
function plainSpaces(s: string): string {
  return s.replace(/[\u202f\u00a0]/g, " ");
}

function reaches1000(value: number, digits: number): boolean {
  return Number(value.toFixed(digits)) >= 1000;
}

function compactAbs(a: number): string {
  if (a >= 1e9 || (a >= 1e6 && reaches1000(a / 1e6, 2))) return `${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6 || (a >= 1e3 && reaches1000(a / 1e3, 1))) return `${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3 || Math.round(a) >= 1000) return `${(a / 1e3).toFixed(1)}K`;
  return Math.round(a).toString();
}

/** Compact dollars: $950, $12.3K, $1.23M, $1.25B. */
export function fmtUsd(n: number | null | undefined): string {
  if (!isNum(n)) return DASH;
  const body = compactAbs(Math.abs(n));
  return `${n < 0 && body !== "0" ? "-" : ""}$${body}`;
}

/** Whole dollars with grouping: $1,234,567. */
export function fmtUsdFull(n: number | null | undefined): string {
  if (!isNum(n)) return DASH;
  return usdFull.format(Math.round(n)).replace("-$0", "$0");
}

const pctFormats = new Map<number, Intl.NumberFormat>();

function pctFormat(digits: number): Intl.NumberFormat {
  let f = pctFormats.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    pctFormats.set(digits, f);
  }
  return f;
}

/** A fraction as a percentage. Signed ("+12.3%") by default; a rounded zero is never signed. */
export function fmtPct(
  x: number | null | undefined,
  opts: { signed?: boolean; digits?: number } = {},
): string {
  if (!isNum(x)) return DASH;
  const { signed = true, digits = 1 } = opts;
  const pct = x * 100;
  const rounded = Number(pct.toFixed(digits));
  const body = pctFormat(digits).format(Math.abs(rounded));
  if (rounded === 0) return `${body}%`;
  const sign = rounded < 0 ? "-" : signed ? "+" : "";
  return `${sign}${body}%`;
}

/** Share counts: grouped, up to 2 decimals for fractional shares. */
export function fmtShares(n: number | null | undefined): string {
  if (!isNum(n)) return DASH;
  return shares.format(n);
}

/**
 * "2024-01-15" -> "Jan 15, 2024". A date-only string stays on its calendar day in every
 * time zone; a timestamp is shown on its date in US Eastern (the SEC's clock).
 */
export function fmtDate(isoDate: string | null | undefined): string {
  if (!isoDate) return DASH;
  const m = DATE_ONLY.exec(isoDate);
  if (m) return dateUtc.format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))));
  const t = new Date(isoDate);
  return Number.isNaN(t.getTime()) ? DASH : dateEt.format(t);
}

/** "2024-01-15T21:30:12Z" -> "Jan 15, 2024 4:30 PM ET". */
export function fmtDateET(isoDateTime: string | null | undefined): string {
  if (!isoDateTime) return DASH;
  const t = new Date(isoDateTime);
  if (Number.isNaN(t.getTime())) return DASH;
  return plainSpaces(`${dateEt.format(t)} ${timeEt.format(t)} ET`);
}

/** "30s ago", "5m ago", "3h ago", "2d ago"; older than 30 days shows the date. */
export function fmtRelative(isoDateTime: string, now: Date = new Date()): string {
  const t = new Date(isoDateTime);
  if (Number.isNaN(t.getTime())) return DASH;
  const s = Math.floor((now.getTime() - t.getTime()) / 1000);
  if (s < 1) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return fmtDate(isoDateTime);
}

export const NOT_ENOUGH_DATA = "Not enough data yet";

const CONFIDENCE_LABEL = { low: "Low", medium: "Medium", high: "High" } as const;

/** "78 · High"; a missing score means the profile has no complete decisions yet. */
export function ratingLabel(
  score: number | null,
  confidence: "low" | "medium" | "high" | null,
): string {
  if (score === null || score === undefined) return NOT_ENOUGH_DATA;
  return confidence ? `${score} · ${CONFIDENCE_LABEL[confidence]}` : `${score}`;
}
