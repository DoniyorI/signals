import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api } from "@/api/client";
import { BasisToggle } from "@/components/controls/BasisToggle";
import { EquityChart } from "@/components/charts/EquityChart";
import { WindowsTable } from "@/components/data/WindowsTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
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
      ) : (
        <>
          <EquityChart points={query.data.points} />
          <WindowsTable windows={query.data.windows} />
        </>
      )}
    </section>
  );
}
