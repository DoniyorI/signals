import type { useCoverage } from "@/hooks/useCoverage";
import { usePriceLoadStatus } from "@/hooks/usePriceLoadStatus";
import { useState } from "react";
import { SecLink } from "@/components/data/SecLink";
import { ErrorState } from "@/components/state/ErrorState";
import { Button } from "@/components/ui/button";
import { fmtDate, fmtDateET, fmtPct, fmtShares } from "@/lib/format";

const familyLabels = { ownership: "Ownership (3/4/5)", form144: "Form 144", stakes: "Stakes (13D/G)", "13f": "13F" };
const statusLabels = { complete: "Complete", gap: "Gap", in_progress: "In progress", unknown: "Unknown", not_supported: "Not supported" };
const pctLabel = (pct: number | null) => pct == null ? "Unknown" : fmtPct(pct, { signed: false });

/** Full matrices stay in native, keyboard-accessible disclosures. Tables scroll within this
 * section, while headline coverage and unavailable accession failures remain easy to see. */
export function CompletenessSection({ query }: { query: ReturnType<typeof useCoverage> }) {
  const report = query.data;
  const priceStatus = usePriceLoadStatus(!!report);
  const [filingsOpen, setFilingsOpen] = useState(false);
  const [fundsOpen, setFundsOpen] = useState(false);
  const [transactionsOpen, setTransactionsOpen] = useState(false);
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const fundPeriods = [...new Map((report?.funds.quarters ?? []).map((quarter) =>
    [quarter.period, `${quarter.year} Q${quarter.quarter}`])).entries()].sort(([left], [right]) => right.localeCompare(left));
  const fundPeriod = selectedPeriod && fundPeriods.some(([period]) => period === selectedPeriod) ? selectedPeriod : fundPeriods[0]?.[0] ?? "";
  return <section aria-label="Completeness" className="min-w-0 rounded-md border border-border bg-card p-4">
    <h2 className="mb-3 text-base font-semibold">Completeness</h2>
    {!report ? query.isPending ? <p className="text-sm text-muted-foreground">Loading completeness report…</p> :
      <ErrorState title="Completeness report didn't load" description={query.error?.message}
        action={<Button variant="outline" onClick={() => { void query.refetch(); }}>Try again</Button>} /> : <>
      {query.isError && <p role="alert" className="mb-3 text-sm text-neg">Completeness refresh failed. Showing the last successful snapshot.</p>}
      <p className="mb-4 text-xs text-muted-foreground">As of {fmtDate(report.as_of)} · <span>{report.checked_at
        ? `Last checked ${fmtDateET(report.checked_at)}` : "Completeness has not been checked yet."}</span></p>
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <CoverageMetric label="Price history" pct={report.prices.pct}
          detail={`${fmtShares(report.prices.covered)} / ${fmtShares(report.prices.total)} symbols through ${fmtDate(report.prices.through)}`} />
        <CoverageMetric label="Returns from filing (6m)" pct={report.returns.filed.pct}
          detail={`${fmtShares(report.returns.filed.covered)} / ${fmtShares(report.returns.filed.eligible)} eligible decisions`} />
        <CoverageMetric label="Returns from trade (6m)" pct={report.returns.executed.pct}
          detail={`${fmtShares(report.returns.executed.covered)} / ${fmtShares(report.returns.executed.eligible)} eligible decisions`} />
        <CoverageMetric label="Tracked fund quarters" pct={report.funds.pct}
          detail={`${fmtShares(report.funds.covered)} / ${fmtShares(report.funds.total)} quarters across ${fmtShares(report.funds.tracked)} tracked funds`} />
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">{priceStatus.explanation ?? (
        report.prices.loading ? priceStatus.state === "running" ? "Price loading is active" :
          "Price work is queued or running. Check Backfill for current progress." : "No price load is active"
      )}</p>
      <p className="mt-1 text-xs text-muted-foreground">Return coverage includes decisions whose six-month horizon has elapsed.</p>
      <div className="mt-5 flex min-w-0 flex-col gap-4">
        <details className="min-w-0" onToggle={(event) => setFilingsOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-sm font-medium">Filing completeness by quarter ({report.quarters.length} rows)</summary>
          <p className="my-2 text-xs text-muted-foreground">Target: 99.5% per family in completed quarters. Current-quarter counts exclude today and remain in progress.</p>
          {filingsOpen && <div className="max-w-full overflow-x-auto">
            <table aria-label="Filing completeness by quarter" className="w-full text-left text-sm">
              <thead><tr>{["Quarter", "Family", "SEC indexed", "Stored", "Coverage", "Status", "Coverage starts", "Compared through", "Index through"].map((label) =>
                <th key={label} scope="col" className="whitespace-nowrap border-b px-3 py-2 text-xs font-medium text-muted-foreground">{label}</th>)}</tr></thead>
              <tbody>{report.quarters.map((quarter) => <tr key={`${quarter.year}-${quarter.quarter}-${quarter.family}`}>
                <th scope="row" className="whitespace-nowrap border-b px-3 py-2 font-medium">{quarter.year} Q{quarter.quarter}</th>
                <td className="whitespace-nowrap border-b px-3 py-2">{familyLabels[quarter.family]}</td>
                <td className="border-b px-3 py-2 tabular-nums">{quarter.indexed == null ? "Not checked" : fmtShares(quarter.indexed)}</td>
                <td className="border-b px-3 py-2 tabular-nums">{fmtShares(quarter.stored)}</td>
                <td className="border-b px-3 py-2 tabular-nums">{pctLabel(quarter.pct)}</td>
                <td className={`whitespace-nowrap border-b px-3 py-2 ${quarter.status === "gap" ? "text-warn" : ""}`}>{statusLabels[quarter.status]}</td>
                <td className="whitespace-nowrap border-b px-3 py-2">{fmtDate(quarter.coverage_start)}</td>
                <td className="whitespace-nowrap border-b px-3 py-2">{fmtDate(quarter.through)}</td>
                <td className="whitespace-nowrap border-b px-3 py-2">{quarter.indexed_through ? fmtDate(quarter.indexed_through) : "Unknown"}</td>
              </tr>)}</tbody>
            </table>
          </div>}
        </details>
        <details className="min-w-0" onToggle={(event) => setFundsOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-sm font-medium">Tracked fund quarter details ({report.funds.quarters.length} rows)</summary>
          {fundsOpen && <>
          <label className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">Fund quarter
            <select value={fundPeriod} onChange={(event) => setSelectedPeriod(event.target.value)}
              className="rounded border border-border bg-background px-2 py-1 text-sm text-foreground">
              {fundPeriods.map(([period, label]) => <option key={period} value={period}>{label}</option>)}
            </select>
          </label>
          <div className="mt-2 max-w-full overflow-x-auto">
            <table aria-label="Tracked fund quarter coverage" className="w-full text-left text-sm">
              <thead><tr>{["Fund CIK", "Quarter", "Period", "Coverage"].map((label) =>
                <th key={label} scope="col" className="whitespace-nowrap border-b px-3 py-2 text-xs font-medium text-muted-foreground">{label}</th>)}</tr></thead>
              <tbody>{report.funds.quarters.filter((quarter) => quarter.period === fundPeriod).map((quarter) => <tr key={`${quarter.cik}-${quarter.year}-${quarter.quarter}`}>
                <th scope="row" className="border-b px-3 py-2 font-medium"><a className="text-link hover:underline" href={`/fund/${quarter.cik}`}>{quarter.cik}</a></th>
                <td className="whitespace-nowrap border-b px-3 py-2">{quarter.year} Q{quarter.quarter}</td>
                <td className="whitespace-nowrap border-b px-3 py-2">{fmtDate(quarter.period)}</td>
                <td className={`border-b px-3 py-2 ${quarter.present ? "" : "text-warn"}`}>{quarter.present ? "Present" : "Missing"}</td>
              </tr>)}</tbody>
            </table>
          </div>
          </>}
        </details>
        <details className="min-w-0" onToggle={(event) => setTransactionsOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-sm font-medium">Insider transactions by year</summary>
          {transactionsOpen && <div className="mt-2 max-w-full overflow-x-auto">
            <table aria-label="Insider transactions by year" className="w-full text-left text-sm">
              <thead><tr><th scope="col" className="border-b px-3 py-2">Year</th><th scope="col" className="border-b px-3 py-2">Transactions</th></tr></thead>
              <tbody>{report.insider_transactions.map((year) => <tr key={year.year}>
                <th scope="row" className="border-b px-3 py-2 font-medium">{year.year}</th>
                <td className="border-b px-3 py-2 tabular-nums">{fmtShares(year.count)}</td>
              </tr>)}</tbody>
            </table>
          </div>}
        </details>
        <details open={report.unavailable.length > 0} className="min-w-0">
          <summary className="cursor-pointer text-sm font-medium">Unavailable accessions ({report.unavailable.length})</summary>
          {report.unavailable.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No accessions marked unavailable</p> :
            <ul className="mt-2 space-y-2">{report.unavailable.map((item) => <li key={item.accession_no} className="break-words rounded border border-border p-3 text-sm">
              <SecLink href={`https://www.sec.gov/Archives/edgar/data/${item.cik}/${item.accession_no.replaceAll("-", "")}/`} label={item.accession_no} />
              <p className="mt-1">{familyLabels[item.family]} · {item.year} Q{item.quarter}</p>
              <p className="mt-1 text-warn">Retries stopped after {item.attempts} attempts</p>
              <p className="mt-1 text-neg">{item.error}</p>
              <p className="mt-1 text-xs text-muted-foreground">Updated {fmtDateET(item.updated_at)}</p>
            </li>)}</ul>}
        </details>
      </div>
    </>}
  </section>;
}

function CoverageMetric({ label, pct, detail }: { label: string; pct: number | null; detail: string }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="mt-1 text-lg tabular-nums">{pctLabel(pct)}</dd>
    <dd className="mt-1 text-xs text-muted-foreground">{detail}</dd></div>;
}
