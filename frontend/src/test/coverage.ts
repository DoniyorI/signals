/** Complete API response for tests that exercise loading and failed coverage reads. */
export function coverageFixture({ loading = false, pct = 1, missingSymbols = [] as string[] } = {}) {
  return {
    as_of: "2024-06-07", checked_at: "2024-06-07T21:12:47Z",
    quarters: [{ year: 2024, quarter: 2, family: "ownership", indexed: 100, stored: 100,
      pct: 1, status: "in_progress", coverage_start: "2016-01-01", through: "2024-06-06", indexed_through: "2024-06-06" }],
    insider_transactions: [{ year: 2024, count: 25 }],
    prices: { total: 100, covered: Math.round(pct * 100), pct, through: "2024-06-07", loading, missing_symbols: missingSymbols },
    returns: { filed: { eligible: 20, covered: 20, pct: 1 }, executed: { eligible: 20, covered: 20, pct: 1 } },
    funds: { tracked: 2, total: 2, covered: 2, pct: 1, quarters: [
      { cik: 3000001, year: 2024, quarter: 1, period: "2024-03-31", present: true },
      { cik: 3000002, year: 2024, quarter: 1, period: "2024-03-31", present: true },
    ] },
    unavailable: [],
  };
}
