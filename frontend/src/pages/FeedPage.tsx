import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useRef } from "react";
import { useSearchParams } from "react-router";
import { api } from "@/api/client";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { FeedFilters } from "./feed/FeedFilters";
import { feedColumns } from "./feed/feedColumns";
import { FeedSummaryStrip } from "./feed/FeedSummaryStrip";

const PAGE_LIMIT = 50;
const POLL_INTERVAL_MS = 30_000;

function parseNum(raw: string | null): number | undefined {
  if (!raw) return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function commaList(sp: URLSearchParams, key: string): string[] | undefined {
  const raw = sp.get(key);
  return raw ? raw.split(",").filter(Boolean) : undefined;
}

/** Turns the page's URL filters into `/api/feed` query params. Exported for the page's tests. */
export function feedQueryParams(sp: URLSearchParams, cursor?: string) {
  const direction = sp.get("direction");
  return {
    forms: commaList(sp, "forms"),
    direction: direction ? [direction] : undefined,
    roles: commaList(sp, "roles"),
    sectors: commaList(sp, "sectors"),
    badges: commaList(sp, "badges"),
    min_value: parseNum(sp.get("min_value")),
    max_value: parseNum(sp.get("max_value")),
    min_mcap: parseNum(sp.get("min_mcap")),
    max_mcap: parseNum(sp.get("max_mcap")),
    max_lag_days: parseNum(sp.get("max_lag_days")),
    // "Hide 10b5-1" defaults on, i.e. this is `false` unless the URL says otherwise.
    include_10b5_1: sp.get("include_10b5_1") === "true",
    trade_from: sp.get("trade_from") || undefined,
    trade_to: sp.get("trade_to") || undefined,
    filed_from: sp.get("filed_from") || undefined,
    filed_to: sp.get("filed_to") || undefined,
    cursor,
    limit: PAGE_LIMIT,
  };
}

function directionRowClass(direction: string | null): string | undefined {
  if (direction === "buy") return "border-l-[3px] border-l-pos";
  if (direction === "sell") return "border-l-[3px] border-l-neg";
  return undefined;
}

export default function FeedPage() {
  const [searchParams] = useSearchParams();
  const filtersKey = searchParams.toString();
  const scrollHostRef = useRef<HTMLDivElement>(null);

  const feed = useInfiniteQuery({
    queryKey: ["feed", filtersKey],
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const { data } = await api.GET("/api/feed", {
        params: { query: feedQueryParams(searchParams, pageParam) },
      });
      if (!data) throw new Error("Could not load the feed.");
      return data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const items = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const topAcceptedAt = items[0]?.accepted_at ?? null;

  // A lightweight, independent poll of just the newest page: comparing it against the
  // currently *displayed* top row detects new filings without disturbing `feed`'s own cache,
  // so rows never jump while someone is reading them.
  const topPoll = useQuery({
    queryKey: ["feed-top", filtersKey],
    queryFn: async () => {
      const { data } = await api.GET("/api/feed", {
        params: { query: feedQueryParams(searchParams) },
      });
      return data ?? null;
    },
    enabled: items.length > 0,
    refetchInterval: POLL_INTERVAL_MS,
  });

  const newCount =
    topPoll.data && topAcceptedAt
      ? topPoll.data.items.filter((item) => (item.accepted_at ?? "") > topAcceptedAt).length
      : 0;

  function showNewFilings() {
    scrollHostRef.current?.querySelector(".overflow-auto")?.scrollTo({ top: 0, behavior: "smooth" });
    void feed.refetch();
  }

  const csvHref = `/api/feed?${new URLSearchParams(
    Object.entries(feedQueryParams(searchParams))
      .filter(([, v]) => v !== undefined)
      .flatMap(([k, v]) => (Array.isArray(v) ? v.map((x) => [k, String(x)]) : [[k, String(v)]])),
  ).toString()}&format=csv`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">Live feed</h1>
      </div>
      <FeedSummaryStrip />
      <FeedFilters />
      {newCount > 0 && (
        <button
          type="button"
          onClick={showNewFilings}
          className="inline-flex w-fit items-center gap-1.5 self-start rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground shadow-xs hover:bg-muted"
        >
          <Bell className="size-3.5" aria-hidden />
          {newCount} new filing{newCount === 1 ? "" : "s"}
        </button>
      )}
      <div ref={scrollHostRef}>
        {feed.status === "pending" ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
        ) : feed.status === "error" ? (
          <ErrorState
            title="The feed didn't load"
            action={
              <button type="button" onClick={() => feed.refetch()} className="text-sm text-link hover:underline">
                Try again
              </button>
            }
          />
        ) : (
          <DataTable
            columns={feedColumns}
            data={items}
            getRowId={(item) => item.accession_no}
            onEndReached={feed.hasNextPage ? () => feed.fetchNextPage() : undefined}
            isFetchingMore={feed.isFetchingNextPage}
            csvHref={csvHref}
            rowClassName={(item) => directionRowClass(item.direction)}
            empty={<EmptyState title="No filings match these filters" />}
          />
        )}
      </div>
    </div>
  );
}
