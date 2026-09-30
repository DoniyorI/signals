import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type Schema } from "@/api/client";
import { BadgeChip } from "@/components/data/BadgeChip";
import { DataTable } from "@/components/data/DataTable";
import { PlanChip } from "@/components/data/PlanChip";
import { ReturnCell } from "@/components/data/ReturnCell";
import { SecLink } from "@/components/data/SecLink";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import type { Basis } from "@/components/controls/BasisToggle";
import { fmtDate, fmtPct, fmtUsd } from "@/lib/format";
import { companyHref } from "@/pages/feed/feedColumns";

type DecisionOut = Schema<"DecisionOut">;

const HORIZONS = ["1m", "3m", "6m", "12m"] as const;

function excessOf(d: DecisionOut, horizon: (typeof HORIZONS)[number]): number | null | undefined {
  return d.returns.find((r) => r.horizon === horizon)?.excess_spy;
}

const columnHelper = createColumnHelper<DecisionOut>();

const columns = [
  columnHelper.accessor("first_trade_date", {
    header: "Date",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
  columnHelper.display({
    id: "company",
    header: "Company",
    cell: ({ row }) => (
      <Link to={companyHref(row.original.issuer)} className="text-link hover:underline">
        {row.original.issuer.ticker ?? row.original.issuer.name}
      </Link>
    ),
  }),
  columnHelper.accessor("direction", {
    header: "Direction",
    cell: ({ getValue }) => (getValue() === "buy" ? "Buy" : "Sell"),
  }),
  columnHelper.accessor("value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("stake_change_pct", {
    header: "Stake change",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue())}</span>,
  }),
  columnHelper.display({
    id: "badges",
    header: "Badges",
    cell: ({ row }) => (
      <span className="flex flex-wrap gap-1">
        {row.original.badges.map((badge) => (
          <BadgeChip key={badge} badge={badge} />
        ))}
        <PlanChip flag={row.original.plan_10b5_1} />
      </span>
    ),
  }),
  ...HORIZONS.map((horizon) =>
    columnHelper.display({
      id: horizon,
      header: horizon,
      cell: ({ row }: { row: { original: DecisionOut } }) => <ReturnCell value={excessOf(row.original, horizon)} />,
    }),
  ),
  columnHelper.display({
    id: "sec",
    header: "",
    cell: ({ row }) => <SecLink href={row.original.sec_url} label="SEC" />,
  }),
];

// See ledger Ruling F4.1: a `createColumnHelper` array can't be assigned directly to
// `DataTable`'s `columns: ColumnDef<T>[]` prop in this TanStack Table version.
const decisionColumns = columns as unknown as ColumnDef<DecisionOut>[];

/** Decisions: date, company, direction, value, stake change, badges, and the 1m/3m/6m/12m
 * excess returns for the current basis (spec 11, insider profile). */
export function DecisionsTab({ cik, basis, include }: { cik: number; basis: Basis; include: boolean }) {
  const query = useInfiniteQuery({
    queryKey: ["insider-decisions", cik, basis, include],
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const { data } = await api.GET("/api/insiders/{cik}/decisions", {
        params: { path: { cik }, query: { basis, include_10b5_1: include, cursor: pageParam, limit: 50 } },
      });
      if (!data) throw new Error("Could not load decisions.");
      return data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  if (query.status === "pending") return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  if (query.status === "error") {
    return (
      <ErrorState
        title="Decisions didn't load"
        action={
          <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
            Try again
          </button>
        }
      />
    );
  }

  const items = query.data.pages.flatMap((page) => page.items);

  return (
    <DataTable
      columns={decisionColumns}
      data={items}
      getRowId={(d) => String(d.id)}
      onEndReached={query.hasNextPage ? () => query.fetchNextPage() : undefined}
      isFetchingMore={query.isFetchingNextPage}
      empty={<EmptyState title="No decisions yet" />}
    />
  );
}
