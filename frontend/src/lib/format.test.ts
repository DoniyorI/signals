import {
  fmtDate,
  fmtDateET,
  fmtPct,
  fmtRelative,
  fmtShares,
  fmtUsd,
  fmtUsdFull,
  ratingLabel,
} from "@/lib/format";

it("formats usd", () => {
  expect(fmtUsd(1234567)).toBe("$1.23M");
  expect(fmtUsd(950)).toBe("$950");
  expect(fmtUsd(1_250_000_000)).toBe("$1.25B");
  expect(fmtUsd(12_345)).toBe("$12.3K");
  expect(fmtUsd(-2_500_000)).toBe("-$2.50M");
  expect(fmtUsd(null)).toBe("—");
  expect(fmtUsdFull(1234567)).toBe("$1,234,567");
});

it("promotes compact usd to the next unit when rounding reaches it", () => {
  expect(fmtUsd(999_960)).toBe("$1.00M");
  expect(fmtUsd(999.6)).toBe("$1.0K");
  expect(fmtUsd(0)).toBe("$0");
  expect(fmtUsd(undefined)).toBe("—");
  expect(fmtUsdFull(null)).toBe("—");
  expect(fmtUsdFull(-950.4)).toBe("-$950");
});

it("formats pct", () => {
  expect(fmtPct(0.1234)).toBe("+12.3%");
  expect(fmtPct(-0.05)).toBe("-5.0%");
  expect(fmtPct(0)).toBe("0.0%");
  expect(fmtPct(0.1234, { signed: false })).toBe("12.3%");
  expect(fmtPct(undefined)).toBe("—");
});

it("never shows a signed zero percent", () => {
  expect(fmtPct(-0.0001)).toBe("0.0%");
  expect(fmtPct(0.0004, { digits: 0 })).toBe("0%");
  expect(fmtPct(0.92, { signed: false, digits: 0 })).toBe("92%");
});

it("formats shares and dates", () => {
  expect(fmtShares(12000)).toBe("12,000");
  expect(fmtShares(123.4567)).toBe("123.46");
  expect(fmtDate("2024-01-15")).toBe("Jan 15, 2024");
  expect(fmtDateET("2024-01-15T21:30:12Z")).toBe("Jan 15, 2024 4:30 PM ET");
  expect(fmtRelative("2024-01-15T21:25:00Z", new Date("2024-01-15T21:30:00Z"))).toBe("5m ago");
});

it("keeps dates on their calendar day and handles missing values", () => {
  // A date-only string must not shift to the previous day in western time zones.
  expect(fmtDate("2024-06-30")).toBe("Jun 30, 2024");
  // A timestamp is shown on its date in ET, not UTC.
  expect(fmtDate("2024-07-01T02:00:00Z")).toBe("Jun 30, 2024");
  expect(fmtDate(null)).toBe("—");
  expect(fmtDateET(undefined)).toBe("—");
  expect(fmtShares(null)).toBe("—");
  // Morning filings keep a single space before the meridiem (ICU emits U+202F).
  expect(fmtDateET("2024-03-28T13:05:00Z")).toBe("Mar 28, 2024 9:05 AM ET");
});

it("formats relative times across units", () => {
  const now = new Date("2024-06-10T16:00:00Z");
  expect(fmtRelative("2024-06-10T15:59:30Z", now)).toBe("30s ago");
  expect(fmtRelative("2024-06-10T13:00:00Z", now)).toBe("3h ago");
  expect(fmtRelative("2024-06-08T16:00:00Z", now)).toBe("2d ago");
  // Beyond a month the exact date reads better than a large day count.
  expect(fmtRelative("2024-01-15T21:30:00Z", now)).toBe("Jan 15, 2024");
});

it("labels ratings", () => {
  expect(ratingLabel(78, "high")).toBe("78 · High");
  expect(ratingLabel(null, null)).toBe("Not enough data yet");
  expect(ratingLabel(41, "low")).toBe("41 · Low");
  expect(ratingLabel(null, "medium")).toBe("Not enough data yet");
  expect(ratingLabel(55, null)).toBe("55");
});
