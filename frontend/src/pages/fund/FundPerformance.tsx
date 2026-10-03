import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api } from "@/api/client";
import { BasisToggle } from "@/components/controls/BasisToggle";
import { EquityChart } from "@/components/charts/EquityChart";
import { WindowsTable } from "@/components/data/WindowsTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { CoverageEmptyState } from "@/components/state/CoverageEmptyState";
import { isNotFound, required, retryUnlessNotFound } from "@/lib/httpError";
import { basisParam } from "@/lib/queryParams";

/** The copycat equity curve and windows table for the basis in the URL. A fund with no
 * profile_stats/performance coverage (untracked) 404s, which reads as the spec's own copy: the
 * F7 review-focus test "untracked fund message" (plan 07, Global Constraints "Review Focus"). */
export function FundPerformance({ cik }: { cik: number }) {
  const [searchParams] = useSearchParams();
  const basis = basisParam(searchParams);

  const query = useQuery({
    queryKey: ["fund-performance", cik, basis],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/funds/{cik}/performance", {
        params: { path: { cik }, query: { basis } },
      });
      return required(data, response);
    },
    retry: retryUnlessNotFound,
  });

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">Performance</h2>
        <BasisToggle />
      </div>
      {query.status === "pending" ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : query.status === "error" ? (
        isNotFound(query.error) ? (
          <EmptyState title="Performance is available for tracked funds only" />
        ) : (
          <ErrorState
            title="Performance didn't load"
            action={
              <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
                Try again
              </button>
            }
          />
        )
      ) : query.data.points.length === 0 || query.data.coverage_pct === 0 ? (
        <FundEmptyPerformance cik={cik} noPrices={query.data.coverage_pct === 0} />
      ) : (
        <>
          <EquityChart points={query.data.points} />
          <WindowsTable windows={query.data.windows} />
        </>
      )}
    </section>
  );
}

function FundEmptyPerformance({ cik, noPrices }: { cik: number; noPrices: boolean }) {
  const [searchParams] = useSearchParams();
  const period = searchParams.get("period");
  const holdings = useQuery({
    queryKey: ["fund-holdings", cik, period],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/funds/{cik}/holdings", {
        params: { path: { cik }, query: { period: period ?? undefined } },
      });
      return required(data, response);
    },
  });
  if (holdings.isPending) return <p className="py-10 text-center text-sm text-muted-foreground">Checking price coverage…</p>;
  if (holdings.isError) return <ErrorState title="Performance coverage didn't load" />;
  const rows = holdings.data.rows;
  const unmapped = noPrices && holdings.data.next_cursor === null && rows.length > 0 &&
    rows.every((row) => row.security.ticker === null && row.security.issuer_cik === null);
  return <CoverageEmptyState title="No completed quarterly performance yet" notCovered={unmapped}
    symbols={rows.flatMap((row) => row.security.ticker ? [row.security.ticker] : [])} noPricesWhenIdle={noPrices && rows.length > 0} />;
}
