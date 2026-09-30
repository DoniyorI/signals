import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { Link, useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { AllocationDonut } from "@/components/charts/AllocationDonut";
import { QuarterSelect } from "@/components/controls/QuarterSelect";
import { ChangeChip } from "@/components/data/ChangeChip";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { fmtPct, fmtUsd } from "@/lib/format";
import { companyHref } from "@/pages/feed/feedColumns";

type FundHoldingRow = Schema<"FundHoldingRow">;

const columnHelper = createColumnHelper<FundHoldingRow>();

const columns = [
  columnHelper.display({
    id: "security",
    header: "Security",
    cell: ({ row }) => {
      const sec = row.original.security;
      const name = sec.ticker ?? sec.name ?? sec.cusip;
      return sec.issuer_cik != null ? (
        <Link to={companyHref({ cik: sec.issuer_cik, name: sec.name ?? sec.cusip, ticker: sec.ticker })} className="text-link hover:underline">
          {name}
        </Link>
      ) : (
        <span>{name}</span>
      );
    },
  }),
  columnHelper.display({
    id: "star",
    header: "",
    cell: ({ row }) => (row.original.high_conviction ? <span title="High conviction position">★</span> : null),
  }),
  columnHelper.accessor("value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("weight", {
    header: "Weight",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue(), { signed: false })}</span>,
  }),
  columnHelper.accessor("prev_weight", {
    header: "Prior weight",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue(), { signed: false })}</span>,
  }),
  columnHelper.display({
    id: "change",
    header: "Change",
    cell: ({ row }) => <ChangeChip change={row.original.change} />,
  }),
  columnHelper.accessor("shares_change_pct", {
    header: "Shares change",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue())}</span>,
  }),
  columnHelper.accessor("sector", {
    header: "Sector",
    cell: ({ getValue }) => getValue() ?? "—",
  }),
];

// See ledger Ruling F4.1.
const holdingColumns = columns as unknown as ColumnDef<FundHoldingRow>[];

function rowId(r: FundHoldingRow): string {
  return r.security.cusip;
}

/** Holdings for a chosen quarter — a table (★ marks high-conviction rows, spec 9.7), a
 * separate "Exited this quarter" section, a sector donut, and concentration stats (effective N,
 * top-5 weight) — spec 11, fund page. */
export function FundHoldings({ cik }: { cik: number }) {
  const [searchParams] = useSearchParams();
  const period = searchParams.get("period");

  const query = useQuery({
    queryKey: ["fund-holdings", cik, period],
    queryFn: async () => {
      const { data } = await api.GET("/api/funds/{cik}/holdings", {
        params: { path: { cik }, query: { period: period ?? undefined } },
      });
      if (!data) throw new Error("Could not load holdings.");
      return data;
    },
  });

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">Holdings</h2>
        <QuarterSelect periods={query.data?.periods_available ?? []} />
      </div>
      {query.status === "pending" ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : query.status === "error" ? (
        <ErrorState
          title="Holdings didn't load"
          action={
            <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
              Try again
            </button>
          }
        />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <DataTable
              columns={holdingColumns}
              data={query.data.rows}
              getRowId={rowId}
              empty={<EmptyState title="No holdings this quarter" />}
            />
            <div>
              <AllocationDonut slices={query.data.by_sector} />
              <div className="mt-2 text-xs text-muted-foreground">
                Effective N {query.data.effective_n?.toFixed(1) ?? "—"} · Top 5{" "}
                {fmtPct(query.data.top5_weight, { signed: false })}
              </div>
            </div>
          </div>
          {query.data.exits.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-foreground">Exited this quarter</h3>
              <DataTable columns={holdingColumns} data={query.data.exits} getRowId={rowId} height={200} />
            </div>
          )}
        </>
      )}
    </section>
  );
}
