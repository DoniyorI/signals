import { useState } from "react";
import { useSearchParams } from "react-router";
import { BasisToggle } from "@/components/controls/BasisToggle";
import { TenB51Toggle } from "@/components/controls/TenB51Toggle";
import { ROLES, SECTORS, WINDOWS } from "@/lib/domain";

export function ScreenerFilters({ funds }: { funds: boolean }) {
  const [open, setOpen] = useState(false);
  const [sp, setSp] = useSearchParams();
  function set(key: string, value: string) {
    setSp((old) => { const next = new URLSearchParams(old); if (value) next.set(key, value); else next.delete(key); next.delete("cursor"); return next; });
  }
  function choices(key: string, label: string, values: readonly string[]) {
    const selected = sp.get(key)?.split(",") ?? [];
    return <fieldset className="space-y-2"><legend className="font-medium">{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-2">{values.map((value) => <label key={value} className="flex items-center gap-2">
        <input type="checkbox" checked={selected.includes(value)} onChange={(e) => set(key, (e.target.checked ? [...selected, value] : selected.filter((v) => v !== value)).join(","))} />{value}
      </label>)}</div></fieldset>;
  }
  function field(key: string, label: string, type = "number", min?: number, max?: number) {
    const percent = key === "min_return" || key === "max_return";
    const raw = sp.get(key);
    return <label className="flex flex-col gap-1">{label}<input className="w-40 rounded border border-border bg-background px-2 py-1"
      type={type} min={min} max={max} step={key === "min_decisions" || key === "min_rating" ? 1 : "any"}
      value={percent && raw ? Number(raw) * 100 : raw ?? ""}
      onChange={(e) => set(key, percent && e.target.value ? String(Number(e.target.value) / 100) : e.target.value)} /></label>;
  }
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center gap-3">
      <BasisToggle />{!funds && <TenB51Toggle />}
      <label className="flex items-center gap-2 text-sm">Return window
        <select className="rounded border border-border bg-background px-2 py-1" value={sp.get("window") ?? "1y"} onChange={(e) => set("window", e.target.value)}>
          {WINDOWS.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
        </select>
      </label>
      {funds && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sp.get("tracked_only") !== "false"} onChange={(e) => set("tracked_only", String(e.target.checked))} />Tracked funds only</label>}
      <button type="button" className="rounded border border-border px-3 py-1 text-sm" aria-expanded={open} aria-controls="screener-filters" onClick={() => setOpen(!open)}>Filters</button>
    </div>
    {open && <div id="screener-filters" className="space-y-4 rounded border border-border bg-card p-4 text-sm">
      {!funds && choices("roles", "Roles", ROLES)}
      {choices("sectors", "Sectors", SECTORS)}
      {choices("confidence", "Confidence", ["low", "medium", "high"])}
      {choices("risk", "Risk", ["low", "medium", "high"])}
      <div className="flex flex-wrap gap-3">
        {field("min_rating", "Minimum rating", "number", 0, 100)}
        {field("min_return", "Minimum return (%)")}{field("max_return", "Maximum return (%)")}
        {!funds && <>{field("min_decisions", "Minimum decisions", "number", 1)}{field("last_trade_from", "Last trade from", "date")}{field("last_trade_to", "Last trade to", "date")}</>}
      </div>
    </div>}
  </div>;
}
