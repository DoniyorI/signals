import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api, type Schema } from "@/api/client";
import { SecLink } from "@/components/data/SecLink";
import { ErrorState } from "@/components/state/ErrorState";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle,
} from "@/components/ui/dialog";
import { DASH, fmtDate, fmtDateET, fmtPct, fmtRelative, fmtShares } from "@/lib/format";
import { required } from "@/lib/httpError";

const statusText = { ok: "All systems normal", warn: "Needs attention", error: "Problem detected" };
const statusClass = { ok: "border-pos/30 bg-pos/10", warn: "border-warn/30 bg-warn/10", error: "border-neg/30 bg-neg/10" };
const coverageLabels: Record<keyof Schema<"Coverage">, string> = {
  decisions_with_prices_pct: "Decisions with prices",
  decisions_last_price_exit_pct: "Decisions using last-price exit",
  cusip_value_mapped_pct: "CUSIP value mapped",
  issuers_with_sector_pct: "Issuers with sector",
};

async function queueJob(body: Schema<"JobRequestIn">) {
  const { data, response } = await api.POST("/api/jobs", { body });
  return required(data, response);
}

export default function HealthPage() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/health");
      return required(data, response);
    },
    refetchInterval: 30_000,
  });

  if (!healthQuery.data) {
    if (healthQuery.isPending) return <p className="py-10 text-center text-muted-foreground">Loading data health…</p>;
    return <ErrorState title="Could not load data health" description={healthQuery.error?.message}
      action={<Button variant="outline" onClick={() => healthQuery.refetch()}>Try again</Button>} />;
  }

  const health = healthQuery.data;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-xl font-semibold">Data health</h1>
          <p className="text-xs text-muted-foreground">Refreshes every 30 seconds · Times in US Eastern</p></div>
        <Button variant="outline" disabled={healthQuery.isFetching} onClick={() => healthQuery.refetch()}>
          {healthQuery.isFetching ? "Refreshing…" : "Refresh now"}
        </Button>
      </header>
      {healthQuery.isError && <p role="alert" className="text-sm text-neg">
        Refresh failed. Showing the last successful snapshot. {healthQuery.error.message}
      </p>}
      <div role={health.status === "ok" ? "status" : "alert"} className={`rounded-md border p-4 ${statusClass[health.status]}`}>
        <p className="font-semibold">{statusText[health.status]}</p>
        {health.sec_blocked_until && <p className="mt-1 text-sm">SEC paused requests until {fmtDateET(health.sec_blocked_until)}</p>}
      </div>
      <Section title="Feed delay">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Metric label="p50" value={health.feed_delay_p50_s === null ? DASH : `${fmtShares(health.feed_delay_p50_s)} s`} />
          <Metric label="p95" value={health.feed_delay_p95_s === null ? DASH : `${fmtShares(health.feed_delay_p95_s)} s`} />
          <Metric label="Last filing seen" value={health.last_filing_seen_at
            ? <time dateTime={health.last_filing_seen_at} title={fmtDateET(health.last_filing_seen_at)}>{fmtRelative(health.last_filing_seen_at)}</time>
            : "No filing seen yet"} />
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">Delay from SEC acceptance to the filing appearing in the feed. Target p95: 120 seconds.</p>
      </Section>
      <Section title="Jobs">
        {health.jobs.length === 0 ? <p className="text-sm text-muted-foreground">No job runs yet</p> :
          <div className="max-w-full overflow-x-auto"><table className="w-full text-left text-sm" aria-label="Jobs">
            <thead><tr>{["Job", "Last status", "Started (ET)", "Finished (ET)", "Last error"].map((label) =>
              <th key={label} scope="col" className="whitespace-nowrap border-b px-3 py-2 text-xs font-medium text-muted-foreground">{label}</th>)}</tr></thead>
            <tbody>{health.jobs.map((job) => <tr key={job.kind}>
              <th scope="row" className="border-b px-3 py-2 font-medium">{job.kind}</th>
              <td className="border-b px-3 py-2">{job.last_status ?? "Not run yet"}</td>
              <td className="whitespace-nowrap border-b px-3 py-2 tabular-nums">{fmtDateET(job.last_started_at)}</td>
              <td className="whitespace-nowrap border-b px-3 py-2 tabular-nums">{fmtDateET(job.last_finished_at)}</td>
              <td className="min-w-40 max-w-md break-words border-b px-3 py-2 text-neg">{job.last_error ?? DASH}</td>
            </tr>)}</tbody>
          </table></div>}
      </Section>
      <Section title="Parse errors">
        {health.parse_errors.length === 0 ? <p className="text-sm text-muted-foreground">No unresolved parse errors</p> :
          <div className="max-w-full overflow-x-auto"><table className="w-full text-left text-sm" aria-label="Parse errors">
            <thead><tr>{["Accession", "Form", "Filed", "Error", "Action"].map((label) =>
              <th key={label} scope="col" className="whitespace-nowrap border-b px-3 py-2 text-xs font-medium text-muted-foreground">{label}</th>)}</tr></thead>
            <tbody>{health.parse_errors.map((error) => <ParseErrorRow key={error.accession_no} error={error} />)}</tbody>
          </table></div>}
      </Section>
      <Section title="Backfill">
        <p className="mb-4 text-sm text-muted-foreground">A restarted backfill continues from saved checkpoints. Work runs in the worker.</p>
        <div className="flex flex-col gap-4">
          {health.backfill.length === 0 && <p className="text-sm text-muted-foreground">No backfill checkpoints yet</p>}
          {health.backfill.map((step) => <BackfillProgress key={step.step} step={step} />)}
          <StartBackfill />
        </div>
      </Section>
      <Section title="Coverage">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(Object.keys(coverageLabels) as (keyof Schema<"Coverage">)[]).map((key) =>
            <Metric key={key} label={coverageLabels[key]} value={fmtPct(health.coverage[key], { signed: false })} />)}
        </dl>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="min-w-0 rounded-md border border-border bg-card p-4" aria-label={title}>
    <h2 className="mb-3 text-base font-semibold">{title}</h2>{children}
  </section>;
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-lg tabular-nums">{value}</dd></div>;
}

function ParseErrorRow({ error }: { error: Schema<"ParseErrorOut"> }) {
  const client = useQueryClient();
  const reparse = useMutation({
    mutationFn: () => queueJob({ kind: "reparse", params: { accessions: [error.accession_no] } }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["health"] }); },
  });
  return <tr>
    <th scope="row" className="whitespace-nowrap border-b px-3 py-2 font-normal"><SecLink href={error.sec_url} label={error.accession_no} /></th>
    <td className="border-b px-3 py-2">{error.form_type}</td>
    <td className="whitespace-nowrap border-b px-3 py-2">{fmtDate(error.filed_date)}</td>
    <td className="min-w-40 max-w-md break-words border-b px-3 py-2 text-neg">{error.error}</td>
    <td className="min-w-36 border-b px-3 py-2">
      <Button size="sm" variant="outline" disabled={reparse.isPending} onClick={() => reparse.mutate()}>
        {reparse.isPending ? "Queuing…" : "Reparse"}
      </Button>
      {reparse.isSuccess && <p role="status" className="mt-1 text-xs">Reparse queued (job {reparse.data.id})</p>}
      {reparse.isError && <p role="alert" className="mt-1 text-xs text-neg">Could not queue reparse: {reparse.error.message}</p>}
    </td>
  </tr>;
}

function BackfillProgress({ step }: { step: Schema<"BackfillStep"> }) {
  const percent = step.total_units !== null && step.total_units > 0
    ? Math.min(100, Math.max(0, step.done_units / step.total_units * 100)) : undefined;
  return <div>
    <div className="mb-1 flex flex-wrap justify-between gap-2 text-sm">
      <span className="font-medium">{step.step}</span><span className="text-muted-foreground">{step.status}</span>
    </div>
    <div role="progressbar" aria-label={step.step} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}
      aria-valuetext={percent === undefined ? `${step.done_units} units; total not known yet` : `${percent.toFixed(1)}%`}
      className="h-2 overflow-hidden rounded bg-muted">
      <div className={`h-full bg-primary ${percent === undefined ? "w-1/3 animate-pulse" : ""}`} style={percent === undefined ? undefined : { width: `${percent}%` }} />
    </div>
    <div className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground tabular-nums">
      <span>{percent === undefined ? `${fmtShares(step.done_units)} units · Total not known yet`
        : `${fmtShares(step.done_units)} / ${fmtShares(step.total_units)} units · ${percent.toFixed(1)}%`}</span>
      <span>Updated {fmtDateET(step.updated_at)}</span>
    </div>
  </div>;
}

function StartBackfill() {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const backfill = useMutation({
    mutationFn: () => queueJob({ kind: "backfill_all" }),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["health"] });
    },
  });
  return <div>
    <Button disabled={backfill.isPending} onClick={() => { backfill.reset(); setOpen(true); }}>Start full backfill</Button>
    {backfill.isSuccess && <p role="status" className="mt-2 text-sm">Full backfill queued (job {backfill.data.id})</p>}
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogTitle>Start full backfill?</DialogTitle>
        <DialogDescription>The worker will load the full filing and price history, continuing from saved checkpoints. This can take several hours.</DialogDescription>
        {backfill.isError && <p role="alert" className="text-sm text-neg">Could not queue full backfill: {backfill.error.message}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={backfill.isPending} onClick={() => setOpen(false)}>Cancel</Button>
          <Button disabled={backfill.isPending} onClick={() => backfill.mutate()}>{backfill.isPending ? "Queuing…" : "Confirm backfill"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}
