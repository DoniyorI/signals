import { SlidersHorizontal } from "lucide-react";
import { useId } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TenB51Toggle } from "@/components/controls/TenB51Toggle";
import { FORM_FAMILIES, ROLES, SECTORS } from "@/lib/domain";
import { BADGE_LABELS } from "@/lib/badges";
import { useUrlListState, useUrlState } from "@/hooks/useUrlState";

type Direction = "" | "buy" | "sell";

function useDirection(): [Direction, (d: Direction) => void] {
  return useUrlState<Direction>(
    "direction",
    "",
    (raw) => (raw === "buy" || raw === "sell" ? raw : ""),
    (v) => v || null,
  );
}

function useNumberParam(key: string): [string, (v: string) => void] {
  const [value, setValue] = useUrlState<string>(
    key,
    "",
    (raw) => raw ?? "",
    (v) => v || null,
  );
  return [value, setValue];
}

/** A row of toggle pills for a comma-joined multi-select URL filter. */
function PillGroup({ label, options, selected, onChange }: { label: string; options: readonly string[]; selected: string[]; onChange: (v: string[]) => void }) {
  const toggle = (option: string) =>
    onChange(selected.includes(option) ? selected.filter((o) => o !== option) : [...selected, option]);
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-foreground">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <Badge
            key={option}
            variant={selected.includes(option) ? "default" : "outline"}
            className="cursor-pointer select-none font-normal"
            onClick={() => toggle(option)}
          >
            {option}
          </Badge>
        ))}
      </div>
    </fieldset>
  );
}

function RangeField({ label, minKey, maxKey, prefix }: { label: string; minKey: string; maxKey: string; prefix?: string }) {
  const [min, setMin] = useNumberParam(minKey);
  const [max, setMax] = useNumberParam(maxKey);
  const id = useId();
  return (
    <div className="space-y-2">
      <span className="text-sm font-medium text-foreground" id={id}>
        {label}
      </span>
      <div className="flex items-center gap-2" aria-labelledby={id}>
        {prefix && <span className="text-sm text-muted-foreground">{prefix}</span>}
        <Input inputMode="numeric" placeholder="Min" value={min} onChange={(e) => setMin(e.target.value)} />
        <span className="text-muted-foreground">–</span>
        <Input inputMode="numeric" placeholder="Max" value={max} onChange={(e) => setMax(e.target.value)} />
      </div>
    </div>
  );
}

function DateRangeField({ label, fromKey, toKey }: { label: string; fromKey: string; toKey: string }) {
  const [from, setFrom] = useNumberParam(fromKey);
  const [to, setTo] = useNumberParam(toKey);
  const id = useId();
  return (
    <div className="space-y-2">
      <span className="text-sm font-medium text-foreground" id={id}>
        {label}
      </span>
      <div className="flex items-center gap-2" aria-labelledby={id}>
        <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <span className="text-muted-foreground">–</span>
        <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
    </div>
  );
}

const BADGE_KEYS = Object.keys(BADGE_LABELS);

/** All feed filters live in the URL (`useSearchParams`), so views are shareable and
 * reload-safe. The always-visible row covers direction and 10b5-1; everything else — form
 * family, roles, sectors, badges, value/market-cap and date ranges, max lag — sits behind
 * "Filters" so the page keeps its one-filter-row layout. */
export function FeedFilters() {
  const [direction, setDirection] = useDirection();
  const [forms, setForms] = useUrlListState("forms");
  const [roles, setRoles] = useUrlListState("roles");
  const [sectors, setSectors] = useUrlListState("sectors");
  const [badges, setBadges] = useUrlListState("badges");
  const [maxLag, setMaxLag] = useNumberParam("max_lag_days");
  const activeCount =
    forms.length + roles.length + sectors.length + badges.length + (maxLag ? 1 : 0);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={direction || "all"}
        onValueChange={(v) => setDirection(v === "buy" || v === "sell" ? v : "")}
        aria-label="Direction"
      >
        <ToggleGroupItem value="all">All</ToggleGroupItem>
        <ToggleGroupItem value="buy">Buys</ToggleGroupItem>
        <ToggleGroupItem value="sell">Sells</ToggleGroupItem>
      </ToggleGroup>
      <TenB51Toggle />
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="outline" size="sm" className="gap-1.5">
            <SlidersHorizontal className="size-3.5" aria-hidden />
            Filters
            {activeCount > 0 && (
              <Badge variant="secondary" className="px-1.5 font-normal">
                {activeCount}
              </Badge>
            )}
          </Button>
        </SheetTrigger>
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
          </SheetHeader>
          <div className="flex flex-col gap-6 px-4 pb-4">
            <PillGroup label="Form" options={FORM_FAMILIES} selected={forms} onChange={setForms} />
            <PillGroup label="Role" options={ROLES} selected={roles} onChange={setRoles} />
            <PillGroup label="Sector" options={SECTORS} selected={sectors} onChange={setSectors} />
            <PillGroup label="Badges" options={BADGE_KEYS} selected={badges} onChange={setBadges} />
            <RangeField label="Value" minKey="min_value" maxKey="max_value" prefix="$" />
            <RangeField label="Market cap" minKey="min_mcap" maxKey="max_mcap" prefix="$" />
            <DateRangeField label="Trade date" fromKey="trade_from" toKey="trade_to" />
            <DateRangeField label="Filed date" fromKey="filed_from" toKey="filed_to" />
            <div className="space-y-2">
              <label htmlFor="max-lag" className="text-sm font-medium text-foreground">
                Max lag (days)
              </label>
              <Input id="max-lag" inputMode="numeric" value={maxLag} onChange={(e) => setMaxLag(e.target.value)} />
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
