import { describe, expect, it } from "vitest";
import { DEFAULT_MARKER_PALETTE, toCandles, toLines, toMarkers, topSlices } from "./mapping";

describe("toCandles", () => {
  it("maps bars to OHLC candles sorted ascending by date", () => {
    const candles = toCandles([
      { date: "2024-06-05", open: 2, high: 3, low: 1, close: 2.5, adj_close: 2.5, volume: 100 },
      { date: "2024-06-03", open: 1, high: 2, low: 0.5, close: 1.5, adj_close: 1.5, volume: 200 },
    ]);
    expect(candles.map((c) => c.time)).toEqual(["2024-06-03", "2024-06-05"]);
    expect(candles[0]).toMatchObject({ open: 1, high: 2, low: 0.5, close: 1.5 });
  });
});

describe("toMarkers", () => {
  const markers: Array<Parameters<typeof toMarkers>[0][number]> = [
    { date: "2024-06-06", kind: "sell", label: "Sold", value_usd: 1, ref: "b" },
    { date: "2024-06-03", kind: "buy", label: "Bought", value_usd: 1, ref: "a" },
    { date: "2024-06-05", kind: "form144", label: "144", value_usd: null, ref: "c" },
    { date: "2024-06-05", kind: "stake", label: "13D", value_usd: null, ref: "d" },
    { date: "2024-06-04", kind: "cluster", label: "Cluster", value_usd: 1, ref: "e" },
  ];

  it("assigns the shape, position, color and short text per kind", () => {
    const byText = Object.fromEntries(toMarkers(markers).map((m) => [m.text, m]));
    expect(byText.B).toMatchObject({ time: "2024-06-03", shape: "arrowUp", position: "belowBar", color: "#0a7a43" });
    expect(byText.S).toMatchObject({ time: "2024-06-06", shape: "arrowDown", position: "aboveBar", color: "#c42b2b" });
    expect(byText["144"]).toMatchObject({ time: "2024-06-05", shape: "circle", position: "aboveBar", color: "#eda100" });
    expect(byText["13D"]).toMatchObject({ time: "2024-06-05", shape: "square", position: "belowBar", color: "#2a78d6" });
    expect(byText.C).toMatchObject({ time: "2024-06-04", shape: "circle", position: "belowBar", color: "#4a3aa7" });
  });

  it("sorts by time ascending", () => {
    const times = toMarkers(markers).map((m) => m.time);
    expect(times).toEqual([...times].sort());
  });

  it("takes a caller-supplied color palette (canvas can't resolve CSS vars)", () => {
    const [buy] = toMarkers([markers[1]], { ...DEFAULT_MARKER_PALETTE, buy: "#123456" });
    expect(buy.color).toBe("#123456");
  });
});

describe("toLines", () => {
  it("produces one ascending {time,value} series per requested key", () => {
    const lines = toLines(
      [
        { date: "2024-06-04", nav: 1.02, spy: 1.01, qqq: 1.03, sector: 1.0 },
        { date: "2024-06-03", nav: 1.0, spy: 1.0, qqq: 1.0, sector: 1.0 },
      ],
      ["nav", "spy"],
    );
    expect(Object.keys(lines)).toEqual(["nav", "spy"]);
    expect(lines.nav).toEqual([
      { time: "2024-06-03", value: 1.0 },
      { time: "2024-06-04", value: 1.02 },
    ]);
  });
});

describe("topSlices", () => {
  it("passes through when at or under the limit", () => {
    const slices = [{ key: "a", label: "A", value_usd: 10, weight: 1 }];
    expect(topSlices(slices, 8)).toEqual(slices);
  });

  it("collapses the remainder into one Other slice, sorted by value first", () => {
    const slices = Array.from({ length: 10 }, (_, i) => ({
      key: `s${i}`,
      label: `S${i}`,
      value_usd: 10 - i,
      weight: 0.1,
    }));
    const result = topSlices(slices);
    expect(result).toHaveLength(9);
    expect(result.at(-1)).toMatchObject({ key: "other", label: "Other" });
    // The two smallest (value 1 and 2, i.e. s8 and s9) are the ones folded in.
    expect(result.at(-1)!.value_usd).toBe(1 + 2);
    expect(result.at(-1)!.weight).toBeCloseTo(0.2);
  });
});
