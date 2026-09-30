import { Link } from "react-router";
import type { Schema } from "@/api/client";
import { BasisToggle } from "@/components/controls/BasisToggle";
import { TenB51Toggle } from "@/components/controls/TenB51Toggle";
import { RatingPill } from "@/components/data/RatingPill";
import { Button } from "@/components/ui/button";
import { useWatch } from "@/hooks/useWatch";
import { DASH, fmtPct } from "@/lib/format";
import { companyHref } from "@/pages/feed/feedColumns";

type InsiderHeader = Schema<"InsiderHeader">;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="tabular-nums font-medium">{value}</span>
    </div>
  );
}

/** Name, roles by company, rating, headline stats, the filed/executed and 10b5-1 toggles, a
 * watch button, and a cross-link to the matching fund profile when this person also files 13F
 * (spec 11, insider profile). */
export function InsiderHeader({ header }: { header: InsiderHeader }) {
  const watch = useWatch("insider", header.cik);
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{header.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {header.roles.map((role, i) => (
              <span key={role.issuer.cik}>
                {i > 0 && "; "}
                {role.roles.join(", ")} at{" "}
                <Link to={companyHref(role.issuer)} className="text-link hover:underline">
                  {role.issuer.ticker ?? role.issuer.name}
                </Link>
              </span>
            ))}
          </p>
          {header.fund_cik != null && (
            <Link to={`/fund/${header.fund_cik}`} className="text-sm text-link hover:underline">
              Also files 13F as a fund
            </Link>
          )}
        </div>
        <Button
          variant={header.fund_cik != null || watch.isWatched ? "secondary" : "outline"}
          size="sm"
          onClick={() => watch.watch()}
          disabled={watch.isPending || watch.isWatched}
        >
          {watch.isWatched ? "Watching" : "Watch"}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-6">
        <RatingPill rating={header.rating} />
        <Stat label="Avg ROI (6m vs SPY)" value={fmtPct(header.avg_roi_6m)} />
        <Stat label="Hit rate" value={fmtPct(header.hit_rate, { signed: false })} />
        <Stat label="Avg lag" value={header.avg_lag_days != null ? `${header.avg_lag_days.toFixed(1)}d` : DASH} />
        <Stat label="Lag cost" value={fmtPct(header.avg_lag_cost)} />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <BasisToggle />
        <TenB51Toggle />
      </div>
    </div>
  );
}
