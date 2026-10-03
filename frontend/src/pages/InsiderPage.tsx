import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { EquityChart } from "@/components/charts/EquityChart";
import { WindowsTable } from "@/components/data/WindowsTable";
import { ErrorState } from "@/components/state/ErrorState";
import { CoverageEmptyState } from "@/components/state/CoverageEmptyState";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlState } from "@/hooks/useUrlState";
import { isNotFound, required, retryUnlessNotFound } from "@/lib/httpError";
import { basisParam, includeParam } from "@/lib/queryParams";
import { DecisionsTab } from "./insider/DecisionsTab";
import { Form144Tab } from "./insider/Form144Tab";
import { HoldingsTab } from "./insider/HoldingsTab";
import { InsiderHeader } from "./insider/InsiderHeader";
import { TransactionsTab } from "./insider/TransactionsTab";

type Tab = "decisions" | "transactions" | "holdings" | "form144";

function parseTab(raw: string | null): Tab {
  return raw === "transactions" || raw === "holdings" || raw === "form144" ? raw : "decisions";
}

export default function InsiderPage() {
  const { cik: cikParam } = useParams();
  const cik = Number(cikParam);
  const [searchParams] = useSearchParams();
  const basis = basisParam(searchParams);
  const include = includeParam(searchParams);
  const [tab, setTab] = useUrlState<Tab>("tab", "decisions", parseTab, (v) => v);

  const headerQuery = useQuery({
    queryKey: ["insider-header", cik, basis, include],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/insiders/{cik}", {
        params: { path: { cik }, query: { basis, include_10b5_1: include } },
      });
      return required(data, response);
    },
    retry: retryUnlessNotFound,
  });

  const performanceQuery = useQuery({
    queryKey: ["insider-performance", cik, basis, include],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/insiders/{cik}/performance", {
        params: { path: { cik }, query: { basis, include_10b5_1: include } },
      });
      return required(data, response);
    },
    enabled: headerQuery.isSuccess,
  });

  if (headerQuery.status === "pending") {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (headerQuery.status === "error") {
    return isNotFound(headerQuery.error) ? (
      <ErrorState title="Insider not found" />
    ) : (
      <ErrorState
        title="Something went wrong"
        action={
          <button type="button" onClick={() => headerQuery.refetch()} className="text-sm text-link hover:underline">
            Try again
          </button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <InsiderHeader header={headerQuery.data} />
      <section aria-label="Performance" className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-foreground">Performance</h2>
        {performanceQuery.isPending ? <p className="py-10 text-center text-sm text-muted-foreground">Loading performance…</p> :
          performanceQuery.isError ? <ErrorState title="Performance didn't load"
            action={<button type="button" className="text-sm text-link hover:underline" onClick={() => { void performanceQuery.refetch(); }}>Try again</button>} /> :
          performanceQuery.data.points.length === 0 ? <InsiderEmptyPerformance header={headerQuery.data} /> : (
          <>
            <EquityChart points={performanceQuery.data.points} />
            <WindowsTable windows={performanceQuery.data.windows} />
          </>
        )}
      </section>
      <Tabs value={tab} onValueChange={(v) => setTab(parseTab(v))}>
        <TabsList>
          <TabsTrigger value="decisions">Decisions</TabsTrigger>
          <TabsTrigger value="transactions">Transactions</TabsTrigger>
          <TabsTrigger value="holdings">Holdings</TabsTrigger>
          <TabsTrigger value="form144">Form 144</TabsTrigger>
        </TabsList>
        <TabsContent value={tab}>
          {tab === "decisions" && <DecisionsTab cik={cik} basis={basis} include={include} />}
          {tab === "transactions" && <TransactionsTab cik={cik} />}
          {tab === "holdings" && <HoldingsTab cik={cik} />}
          {tab === "form144" && <Form144Tab cik={cik} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Reuse the decisions tab's first page for missing stats; do not scan a long trade history
 * solely to explain an empty view. Count exactly only when every decision is present. */
function InsiderEmptyPerformance({ header }: { header: Schema<"InsiderHeader"> }) {
  const decisions = useInfiniteQuery({
    queryKey: ["insider-decisions", header.cik, header.basis, header.include_10b5_1],
    enabled: header.updated_at === null,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const { data, response } = await api.GET("/api/insiders/{cik}/decisions", {
        params: { path: { cik: header.cik }, query: { basis: header.basis, include_10b5_1: header.include_10b5_1, cursor: pageParam, limit: 50 } },
      });
      return required(data, response);
    },
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  if (header.updated_at === null && decisions.isPending) return <p className="py-10 text-center text-sm text-muted-foreground">Checking completed trades…</p>;
  if (header.updated_at === null && decisions.isError) return <ErrorState title="Performance details didn't load" />;
  const items = decisions.data?.pages.flatMap((page) => page.items) ?? [];
  const completedTrades = header.updated_at !== null ? header.rating.n : decisions.hasNextPage ? null :
    items.filter((decision) => decision.returns.some((r) => r.horizon === "6m" && r.complete)).length;
  return <CoverageEmptyState completedTrades={completedTrades} symbols={items.flatMap((decision) => decision.issuer.ticker ? [decision.issuer.ticker] : [])} />;
}
