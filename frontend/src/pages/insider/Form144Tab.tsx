import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";
import { api, type Schema } from "@/api/client";
import { DataTable } from "@/components/data/DataTable";
import { SecLink } from "@/components/data/SecLink";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { fmtDate, fmtShares, fmtUsd } from "@/lib/format";
import { companyHref } from "@/pages/feed/feedColumns";

type Form144Out = Schema<"Form144Out">;

const STATUS_LABEL: Record<Form144Out["status"], string> = {
  pending: "Pending",
  matched: "Sale executed",
  expired: "Expired",
};

const columnHelper = createColumnHelper<Form144Out>();

const columns = [
  columnHelper.accessor("filed_date", {
    header: "Filed",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
  columnHelper.display({
    id: "issuer",
    header: "Company",
    cell: ({ row }) => (
      <Link to={companyHref(row.original.issuer)} className="text-link hover:underline">
        {row.original.issuer.ticker ?? row.original.issuer.name}
      </Link>
    ),
  }),
  columnHelper.accessor("shares_to_sell", {
    header: "Shares to sell",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtShares(getValue())}</span>,
  }),
  columnHelper.accessor("market_value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("approx_sale_date", {
    header: "Approx. sale date",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
  columnHelper.accessor("broker", {
    header: "Broker",
    cell: ({ getValue }) => getValue() ?? "—",
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: ({ getValue }) => STATUS_LABEL[getValue()],
  }),
  columnHelper.display({
    id: "sec",
    header: "",
    cell: ({ row }) => <SecLink href={row.original.sec_url} label="SEC" />,
  }),
];

// See ledger Ruling F4.1.
const form144Columns = columns as unknown as ColumnDef<Form144Out>[];

/** Form 144 notices of proposed sale, and whether each was later matched to an executed sale
 * (spec 9.8 `form144_matched`; spec 11, insider profile). */
export function Form144Tab({ cik }: { cik: number }) {
  const query = useQuery({
    queryKey: ["insider-form144", cik],
    queryFn: async () => {
      const { data } = await api.GET("/api/insiders/{cik}/form144", { params: { path: { cik } } });
      return data ?? [];
    },
  });

  if (query.status === "pending") return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  if (query.status === "error") {
    return (
      <ErrorState
        title="Form 144 notices didn't load"
        action={
          <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
            Try again
          </button>
        }
      />
    );
  }

  return (
    <DataTable
      columns={form144Columns}
      data={query.data}
      getRowId={(n) => n.accession_no}
      empty={<EmptyState title="No Form 144 notices" />}
    />
  );
}
