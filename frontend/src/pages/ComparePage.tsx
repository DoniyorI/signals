import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { EquityChart } from "@/components/charts/EquityChart";
import { AllocationDonut } from "@/components/charts/AllocationDonut";
import { BasisToggle } from "@/components/controls/BasisToggle";
import { TenB51Toggle } from "@/components/controls/TenB51Toggle";
import { RatingPill } from "@/components/data/RatingPill";
import { ReturnCell } from "@/components/data/ReturnCell";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { WINDOWS } from "@/lib/domain";

export default function ComparePage() {
  const [sp, setSp] = useSearchParams();
  const ids = [...new Set((sp.get("ids") ?? "").split(",").filter((id) => /^(insider|fund):\d+$/.test(id)))].slice(0, 4);
  const [picker, setPicker] = useState(false);
  const [text, setText] = useState("");
  const q = text.trim();
  const basis = sp.get("basis") === "executed" ? "executed" : "filed";
  const include = sp.get("include_10b5_1") === "true";
  const comparison = useQuery({
    queryKey: ["compare", ids.join(","), basis, include], enabled: ids.length > 0,
    queryFn: async () => {
      const { data } = await api.GET("/api/compare", { params: { query: { ids: ids.join(","), basis, include_10b5_1: include } } });
      if (!data) throw new Error("Could not load comparison");
      return data;
    },
  });
  const search = useQuery({
    queryKey: ["search", q], enabled: picker && q.length >= 2 && ids.length < 4,
    queryFn: async () => {
      const { data } = await api.GET("/api/search", { params: { query: { q } } });
      if (!data) throw new Error("Could not search profiles");
      return data;
    },
  });
  function change(nextIds: string[]) {
    setSp((old) => { const next = new URLSearchParams(old); if (nextIds.length) next.set("ids", nextIds.join(",")); else next.delete("ids"); return next; });
  }
  const profiles = comparison.data?.profiles ?? [];
  const hits = [...(search.data?.insiders ?? []), ...(search.data?.funds ?? [])]
    .filter((h) => !ids.includes(`${h.kind}:${h.cik}`));
  const names = new Map(profiles.map((p) => [p.id, p.name]));
  const missing = comparison.isSuccess ? ids.filter((id) => !names.has(id)) : [];

  return <div className="flex min-w-0 flex-col gap-4">
    <h1 className="text-xl font-semibold">Compare</h1>
    <div className="flex flex-wrap items-center gap-3"><BasisToggle /><TenB51Toggle /></div>
    <div className="flex flex-wrap items-center gap-2">
      {ids.map((id) => <span key={id} className="inline-flex items-center gap-2 rounded-full border border-border px-3 py-1 text-sm">
        {names.get(id) ?? id}<button type="button" aria-label={`Remove ${names.get(id) ?? id}`} onClick={() => change(ids.filter((v) => v !== id))}>×</button>
      </span>)}
      <button type="button" className="rounded border border-border px-3 py-1 text-sm disabled:opacity-50" disabled={ids.length >= 4}
        onClick={() => setPicker(!picker)} aria-expanded={picker && ids.length < 4} aria-controls="compare-picker">Add</button>
      <span className="text-xs text-muted-foreground">Up to 4 profiles</span>
    </div>
    {picker && ids.length < 4 && <div id="compare-picker" className="space-y-2 rounded border border-border bg-card p-3">
      <label className="flex flex-col gap-1 text-sm">Search profiles<input type="search" value={text} onChange={(e) => setText(e.target.value)}
        className="rounded border border-border bg-background px-3 py-2" placeholder="Name or fund" /></label>
      {q.length < 2 ? <p className="text-xs text-muted-foreground">Type at least two characters</p> : search.isError ?
        <ErrorState title="Search didn't load" action={<button onClick={() => { void search.refetch(); }}>Try again</button>} /> : search.isPending ? <p>Searching…</p> :
        hits.length === 0 ? <p className="text-sm text-muted-foreground">No matching profiles</p> :
        <ul>{hits.map((hit) => <li key={`${hit.kind}:${hit.cik}`}><button type="button" className="w-full rounded p-2 text-left text-sm hover:bg-muted"
          onClick={() => { change([...ids, `${hit.kind}:${hit.cik}`]); setText(""); setPicker(false); }}>
          {hit.name} <span className="text-muted-foreground">{hit.subtitle}</span>
        </button></li>)}</ul>}
    </div>}
    {ids.length === 0 ? <EmptyState title="Add profiles to compare their track records" /> : comparison.isPending ? <p>Loading…</p> :
      comparison.isError ? <ErrorState title="The comparison didn't load" action={<button onClick={() => { void comparison.refetch(); }}>Try again</button>} /> : <>
        {missing.length > 0 && <p role="status" className="text-sm text-muted-foreground">Profile data unavailable for {missing.join(", ")}. Remove it or try another profile.</p>}
        {profiles.length > 0 && <>
          <section aria-label="Performance comparison" className="min-w-0 rounded border border-border bg-card p-4">
            <h2 className="mb-3 font-medium">Portfolio growth</h2>
            <EquityChart profiles={profiles.map((p) => ({ id: p.id, label: p.name, points: p.curve }))} />
          </section>
          <div className="min-w-0 overflow-auto rounded border border-border">
            <table aria-label="Profile comparison" className="w-full text-sm">
              <thead><tr><th scope="col" className="p-3 text-left">Metric</th>{profiles.map((p) => <th scope="col" key={p.id} className="p-3 text-left whitespace-nowrap">
                <Link className="text-link" to={`/${p.kind}/${p.id.split(":")[1]}`}>{p.name}</Link>
                <div className="text-xs font-normal text-muted-foreground">{p.kind === "fund" ? "Quarterly decisions" : "Six-month decisions"}</div>
              </th>)}</tr></thead>
              <tbody>
                <StatRow label="Rating" profiles={profiles} render={(p) => <RatingPill rating={p.rating} />} />
                <StatRow label="Avg ROI vs SPY" profiles={profiles} render={(p) => <ReturnCell value={p.avg_roi_6m} />} />
                <StatRow label="Hit rate" profiles={profiles} render={(p) => <ReturnCell value={p.hit_rate} />} />
                {WINDOWS.map((w) => <StatRow key={w} label={`${w.toUpperCase()} return`} profiles={profiles} render={(p) => <ReturnCell value={p.windows.find((v) => v.window === w)?.ret} />} />)}
              </tbody>
            </table>
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">{profiles.map((p) => <section key={p.id} className="min-w-0 rounded border border-border bg-card p-4" aria-label={`${p.name} sector allocation`}>
            <h2 className="mb-3 text-sm font-medium">{p.name} · by sector</h2><AllocationDonut slices={p.by_sector} />
          </section>)}</div>
        </>}
      </>}
  </div>;
}

function StatRow({ label, profiles, render }: { label: string; profiles: Schema<"CompareProfile">[]; render: (p: Schema<"CompareProfile">) => React.ReactNode }) {
  return <tr className="border-t border-border"><th scope="row" className="p-3 text-left font-medium whitespace-nowrap">{label}</th>
    {profiles.map((p) => <td key={p.id} className="p-3 tabular-nums">{render(p)}</td>)}
  </tr>;
}
