import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "@/api/client";
import { fmtUsd } from "@/lib/format";
import { companyHref } from "./feedColumns";

const FORM_ORDER = ["3", "4", "5", "144", "13F-HR", "13F-NT", "SCHEDULE 13D", "SCHEDULE 13G"];

function sortForms(counts: Record<string, number>): [string, number][] {
  return Object.entries(counts).sort((a, b) => {
    const [ia, ib] = [FORM_ORDER.indexOf(a[0]), FORM_ORDER.indexOf(b[0])];
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

/** Today's shape of the feed: counts by form, the biggest buys/sells, clusters and late
 * filings (plan 07, F4). */
export function FeedSummaryStrip() {
  const { data } = useQuery({
    queryKey: ["feed-summary"],
    queryFn: async () => {
      const { data } = await api.GET("/api/feed/summary", { params: { query: {} } });
      return data;
    },
  });

  if (!data) return null;

  const totalToday = Object.values(data.counts_by_form).reduce((sum, n) => sum + n, 0);

  return (
    <div className="grid grid-cols-2 gap-4 rounded-md border border-border bg-card p-3 text-sm md:grid-cols-4">
      <div>
        <div className="text-muted-foreground">Today</div>
        <div className="mt-1 tabular-nums">
          {totalToday} filing{totalToday === 1 ? "" : "s"}
          {sortForms(data.counts_by_form).length > 0 && (
            <span className="text-muted-foreground">
              {" "}
              ({sortForms(data.counts_by_form).map(([form, n]) => `${form} ${n}`).join(", ")})
            </span>
          )}
        </div>
      </div>
      <div>
        <div className="text-muted-foreground">Top buys</div>
        <ul className="mt-1 space-y-0.5">
          {data.top_buys.slice(0, 3).map((item) => (
            <li key={item.accession_no} className="truncate tabular-nums">
              {item.issuer ? (
                <Link to={companyHref(item.issuer)} className="text-link hover:underline">
                  {item.issuer.ticker ?? item.issuer.name}
                </Link>
              ) : (
                item.owners[0]?.name
              )}{" "}
              <span className="text-pos">{fmtUsd(item.value_usd)}</span>
            </li>
          ))}
          {data.top_buys.length === 0 && <li className="text-muted-foreground">None</li>}
        </ul>
      </div>
      <div>
        <div className="text-muted-foreground">Top sells</div>
        <ul className="mt-1 space-y-0.5">
          {data.top_sells.slice(0, 3).map((item) => (
            <li key={item.accession_no} className="truncate tabular-nums">
              {item.issuer ? (
                <Link to={companyHref(item.issuer)} className="text-link hover:underline">
                  {item.issuer.ticker ?? item.issuer.name}
                </Link>
              ) : (
                item.owners[0]?.name
              )}{" "}
              <span className="text-neg">{fmtUsd(item.value_usd)}</span>
            </li>
          ))}
          {data.top_sells.length === 0 && <li className="text-muted-foreground">None</li>}
        </ul>
      </div>
      <div>
        <div className="text-muted-foreground">Clusters &amp; late filings</div>
        <div className="mt-1 tabular-nums">
          {data.clusters.length} cluster{data.clusters.length === 1 ? "" : "s"} ·{" "}
          {data.late_filings.length} late
        </div>
      </div>
    </div>
  );
}
