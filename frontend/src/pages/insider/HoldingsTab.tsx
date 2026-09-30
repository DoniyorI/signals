import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";
import { api, type Schema } from "@/api/client";
import { AllocationDonut } from "@/components/charts/AllocationDonut";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { fmtDate, fmtPct, fmtShares, fmtUsd } from "@/lib/format";
import { companyHref } from "@/pages/feed/feedColumns";

type HoldingOut = Schema<"HoldingOut">;

const columnHelper = createColumnHelper<HoldingOut>();

const columns = [
  columnHelper.display({
    id: "issuer",
    header: "Company",
    cell: ({ row }) => (
      <Link to={companyHref(row.original.issuer)} className="text-link hover:underline">
        {row.original.issuer.ticker ?? row.original.issuer.name}
      </Link>
    ),
  }),
  columnHelper.accessor("security_title", { header: "Security" }),
  columnHelper.accessor("shares", {
    header: "Shares",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtShares(getValue())}</span>,
  }),
  columnHelper.accessor("value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("weight", {
    header: "Weight",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue(), { signed: false })}</span>,
  }),
  columnHelper.accessor("sector", {
    header: "Sector",
    cell: ({ getValue }) => getValue() ?? "—",
  }),
  columnHelper.accessor("as_of_date", {
    header: "As of",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
];

// See ledger Ruling F4.1.
const holdingColumns = columns as unknown as ColumnDef<HoldingOut>[];

function holdingRowId(h: HoldingOut): string {
  return `${h.issuer.cik}-${h.security_title}-${h.direct_indirect}`;
}

/** Reported non-derivative positions (valued), derivative holdings (listed only, per spec
 * 9.7), and a by-sector allocation donut (spec 11, insider profile). */
export function HoldingsTab({ cik }: { cik: number }) {
  const query = useQuery({
    queryKey: ["insider-holdings", cik],
    queryFn: async () => {
      const { data } = await api.GET("/api/insiders/{cik}/holdings", { params: { path: { cik } } });
      if (!data) throw new Error("Could not load holdings.");
      return data;
    },
  });

  if (query.status === "pending") return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  if (query.status === "error") {
    return (
      <ErrorState
        title="Holdings didn't load"
        action={
          <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
            Try again
          </button>
        }
      />
    );
  }

  const holdings = query.data;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="flex flex-col gap-4">
        <DataTable
          columns={holdingColumns}
          data={holdings.positions}
          getRowId={holdingRowId}
          empty={<EmptyState title="No reported holdings" />}
        />
        {holdings.derivatives.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium text-foreground">Derivative holdings</h3>
            <DataTable columns={holdingColumns} data={holdings.derivatives} getRowId={holdingRowId} height={200} />
          </div>
        )}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-medium text-foreground">By sector</h3>
        <AllocationDonut slices={holdings.by_sector} />
      </div>
    </div>
  );
}
