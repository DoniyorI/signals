import { Link } from "react-router";
import type { Schema } from "@/api/client";
import { ValueChart } from "@/components/charts/ValueChart";
import { RatingPill } from "@/components/data/RatingPill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useWatch } from "@/hooks/useWatch";
import { fmtPct } from "@/lib/format";

type FundHeader = Schema<"FundHeader">;

/** Name, tracked badge, value-over-time chart, latest positions count, rating, priced
 * coverage %, an insider cross-link, and a watch button (spec 11, fund page). */
export function FundHeader({ fund }: { fund: FundHeader }) {
  const watch = useWatch("fund", fund.cik);
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{fund.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {fund.is_tracked ? (
              <Badge variant="secondary" className="font-normal">
                Tracked
              </Badge>
            ) : (
              <Badge variant="outline" className="font-normal text-muted-foreground">
                Not tracked
              </Badge>
            )}
            {fund.latest_positions != null && <span>{fund.latest_positions} positions</span>}
            {fund.coverage_pct != null && <span>Priced coverage {fmtPct(fund.coverage_pct, { signed: false, digits: 0 })}</span>}
          </p>
          {fund.insider_cik != null && (
            <Link to={`/insider/${fund.insider_cik}`} className="text-sm text-link hover:underline">
              Also an insider
            </Link>
          )}
        </div>
        <div className="flex items-center gap-3">
          <RatingPill rating={fund.rating} />
          <Button
            variant={watch.isWatched ? "secondary" : "outline"}
            size="sm"
            onClick={() => watch.watch()}
            disabled={watch.isPending || watch.isWatched}
          >
            {watch.isWatched ? "Watching" : "Watch"}
          </Button>
        </div>
      </div>
      {fund.value_history.length > 0 && <ValueChart points={fund.value_history} />}
    </div>
  );
}
