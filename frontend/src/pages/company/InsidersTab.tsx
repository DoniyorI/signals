import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { Link, useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { TenB51Toggle } from "@/components/controls/TenB51Toggle";
import { DataTable } from "@/components/data/DataTable";
import { RatingPill } from "@/components/data/RatingPill";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { includeParam } from "@/lib/queryParams";
import { fmtDate, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

type InsiderRosterRow = Schema<"InsiderRosterRow">;

const columnHelper = createColumnHelper<InsiderRosterRow>();

const columns = [
  columnHelper.display({
    id: "owner",
    header: "Insider",
    cell: ({ row }) => (
      <Link to={`/insider/${row.original.owner.cik}`} className="text-link hover:underline">
        {row.original.owner.name}
      </Link>
    ),
  }),
  columnHelper.accessor("roles", {
    header: "Role",
    cell: ({ getValue }) => getValue().join(", "),
  }),
  columnHelper.accessor("last_trade_date", {
    header: "Last trade",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
  columnHelper.accessor("net_12m_usd", {
    header: "Net (12m)",
    cell: ({ getValue }) => {
      const v = getValue();
      return <span className={cn("tabular-nums", v > 0 ? "text-pos" : v < 0 ? "text-neg" : "")}>{fmtUsd(v)}</span>;
    },
  }),
  columnHelper.accessor("n_decisions", { header: "Decisions" }),
  columnHelper.accessor("rating", {
    header: "Rating",
    cell: ({ getValue }) => <RatingPill rating={getValue()} />,
  }),
];

// See ledger Ruling F4.1.
const rosterColumns = columns as unknown as ColumnDef<InsiderRosterRow>[];

/** The insider roster: who trades this stock, their role, last trade, trailing net buying and
 * reliability rating (spec 11, company page). */
export function InsidersTab({ cik }: { cik: number }) {
  const [searchParams] = useSearchParams();
  const include = includeParam(searchParams);

  const query = useQuery({
    queryKey: ["company-insiders", cik, include],
    queryFn: async () => {
      const { data } = await api.GET("/api/companies/{cik}/insiders", {
        params: { path: { cik }, query: { include_10b5_1: include } },
      });
      if (!data) throw new Error("Could not load the insider roster.");
      return data;
    },
  });

  return (
    <div className="flex flex-col gap-3">
      <TenB51Toggle />
      {query.status === "pending" ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : query.status === "error" ? (
        <ErrorState
          title="Insiders didn't load"
          action={
            <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
              Try again
            </button>
          }
        />
      ) : (
        <DataTable
          columns={rosterColumns}
          data={query.data}
          getRowId={(r) => String(r.owner.cik)}
          empty={<EmptyState title="No insiders on record" />}
        />
      )}
    </div>
  );
}
