import type { Schema } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useWatch } from "@/hooks/useWatch";
import { fmtDate, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

type CompanyHeader = Schema<"CompanyHeader">;
type NetBuying = Schema<"NetBuying">;

function NetBuyingStat({ nb }: { nb: NetBuying }) {
  const cls = nb.net_usd > 0 ? "text-pos" : nb.net_usd < 0 ? "text-neg" : "text-foreground";
  return (
    <div className="flex flex-col rounded-md border border-border px-2 py-1">
      <span className="text-xs text-muted-foreground">{nb.window} net</span>
      <span className={cn("tabular-nums text-sm font-medium", cls)}>{fmtUsd(nb.net_usd)}</span>
      <span className="text-xs text-muted-foreground">
        {nb.n_buyers} buyer{nb.n_buyers === 1 ? "" : "s"} · {nb.n_sellers} seller{nb.n_sellers === 1 ? "" : "s"}
      </span>
    </div>
  );
}

/** Name, ticker (with former tickers when the issuer changed symbol), sector, market cap,
 * latest close, net insider buying over 3/6/12 months, and a watch button (spec 11, company
 * page). */
export function CompanyHeader({ company }: { company: CompanyHeader }) {
  const watch = useWatch("company", company.cik);
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{company.name}</h1>
          <p className="mt-1 flex flex-wrap items-baseline gap-2 text-sm text-muted-foreground">
            <span>{company.ticker ?? "No ticker"}</span>
            {company.former_tickers.length > 0 && <span>formerly {company.former_tickers.join(", ")}</span>}
          </p>
          <p className="text-sm text-muted-foreground">
            {company.sector ?? "—"} · Market cap {fmtUsd(company.market_cap_usd)} · Last close{" "}
            {fmtUsd(company.latest_close)}
            {company.latest_close_date && ` (${fmtDate(company.latest_close_date)})`}
          </p>
        </div>
        <Button
          variant={watch.isWatched ? "secondary" : "outline"}
          size="sm"
          onClick={() => watch.watch()}
          disabled={watch.isPending || watch.isWatched}
        >
          {watch.isWatched ? "Watching" : "Watch"}
        </Button>
      </div>
      <div className="flex flex-wrap gap-3">
        {company.net_buying.map((nb) => (
          <NetBuyingStat key={nb.window} nb={nb} />
        ))}
      </div>
    </div>
  );
}
