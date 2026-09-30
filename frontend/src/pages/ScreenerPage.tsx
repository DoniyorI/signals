import { useInfiniteQuery } from "@tanstack/react-query";
import type { OnChangeFn, SortingState } from "@tanstack/react-table";
import { useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { ErrorState } from "@/components/state/ErrorState";
import { WINDOWS, type WindowName } from "@/lib/domain";
import { InsiderScreener } from "./screener/InsiderScreener";
import { FundScreener } from "./screener/FundScreener";
import { ScreenerFilters } from "./screener/ScreenerFilters";

export interface ScreenerTableControls {
  window: WindowName;
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
  onEndReached?: () => void;
  isFetchingMore: boolean;
}

export default function ScreenerPage() {
  const [sp, setSp] = useSearchParams();
  const funds = sp.get("tab") === "funds";
  const window = WINDOWS.includes(sp.get("window") as WindowName) ? sp.get("window") as WindowName : "1y";
  const list = (key: string) => sp.get(key)?.split(",").filter(Boolean);
  const number = (key: string) => {
    const value = sp.get(key);
    return value && Number.isFinite(Number(value)) ? Number(value) : undefined;
  };
  const sort = sp.get("sort") || "rating";
  const order = sp.get("order") === "asc" ? "asc" : "desc";
  const rating = number("min_rating");
  const decisions = number("min_decisions");
  const validation = sp.has("min_rating") && (rating === undefined || !Number.isInteger(rating) || rating < 0 || rating > 100)
    ? "Minimum rating must be a whole number from 0 to 100"
    : !funds && sp.has("min_decisions") && (decisions === undefined || !Number.isInteger(decisions) || decisions < 1)
      ? "Minimum decisions must be a positive whole number" : null;
  const query = {
    sectors: list("sectors"), min_rating: number("min_rating"), confidence: list("confidence"),
    window, min_return: number("min_return"), max_return: number("max_return"), risk: list("risk"),
    basis: sp.get("basis") === "executed" ? "executed" as const : "filed" as const,
    sort, order, limit: 50,
    ...(funds ? { tracked_only: sp.get("tracked_only") !== "false" } : {
      roles: list("roles"), min_decisions: number("min_decisions") ?? 1,
      last_trade_from: sp.get("last_trade_from") || undefined,
      last_trade_to: sp.get("last_trade_to") || undefined,
      include_10b5_1: sp.get("include_10b5_1") === "true",
    }),
  };
  const result = useInfiniteQuery({
    queryKey: ["screener", funds, query],
    enabled: !validation,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const params = { query: { ...query, cursor: pageParam } };
      if (funds) {
        const { data } = await api.GET("/api/screener/funds", { params });
        if (!data) throw new Error("Could not load funds");
        return { funds: data.items, insiders: [] as Schema<"InsiderScreenRow">[], next_cursor: data.next_cursor };
      }
      const { data } = await api.GET("/api/screener/insiders", { params });
      if (!data) throw new Error("Could not load insiders");
      return { insiders: data.items, funds: [] as Schema<"FundScreenRow">[], next_cursor: data.next_cursor };
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const sorting = [{ id: sort, desc: order === "desc" }];
  const controls: ScreenerTableControls = {
    window, sorting,
    onSortingChange: (update) => {
      const next = (typeof update === "function" ? update(sorting) : update)[0];
      setSp((old) => {
        const nextParams = new URLSearchParams(old);
        nextParams.set("sort", next?.id ?? sort);
        nextParams.set("order", next ? next.desc ? "desc" : "asc" : "desc");
        nextParams.delete("cursor");
        return nextParams;
      });
    },
    onEndReached: result.hasNextPage ? () => { void result.fetchNextPage(); } : undefined,
    isFetchingMore: result.isFetchingNextPage,
  };
  const csv = new URLSearchParams(Object.entries(query).filter(([, value]) => value !== undefined)
    .flatMap(([key, value]) => Array.isArray(value) ? value.map((v) => [key, v]) : [[key, String(value)]]));
  csv.set("format", "csv");

  return <div className="flex min-w-0 flex-col gap-4">
    <h1 className="text-xl font-semibold">Screener</h1>
    <div role="tablist" aria-label="Profile type" className="flex gap-2">
      {["insiders", "funds"].map((tab) => <button key={tab} type="button" role="tab"
        aria-selected={funds === (tab === "funds")} aria-controls="screener-results" id={`screener-${tab}`}
        className="rounded-md border border-border px-3 py-1.5 text-sm aria-selected:bg-muted"
        onClick={() => setSp((old) => { const next = new URLSearchParams(old); next.set("tab", tab); next.delete("sort"); next.delete("order"); next.delete("cursor"); return next; })}>
        {tab === "funds" ? "Funds" : "Insiders"}
      </button>)}
    </div>
    <ScreenerFilters funds={funds} />
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <p>{funds ? "Fund ratings use quarterly excess returns." : "Avg ROI and hit rate use six-month decisions."}</p>
      <a className="text-link hover:underline" href={`/api/screener/${funds ? "funds" : "insiders"}?${csv}`}>Export CSV</a>
    </div>
    <div id="screener-results" role="tabpanel" aria-labelledby={`screener-${funds ? "funds" : "insiders"}`}>
      {validation ? <p role="alert" className="text-sm text-neg">{validation}</p> : result.isPending ? <p>Loading…</p> : result.isError ? <ErrorState title="The screener didn't load"
        action={<button onClick={() => { void result.refetch(); }}>Try again</button>} /> : funds ?
        <FundScreener data={result.data.pages.flatMap((p) => p.funds)} {...controls} /> :
        <InsiderScreener data={result.data.pages.flatMap((p) => p.insiders)} {...controls} />}
    </div>
  </div>;
}
