import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { api, type Schema } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/data/DataTable";
import { SecLink } from "@/components/data/SecLink";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { fmtDate, fmtPct } from "@/lib/format";

type StakeOut = Schema<"StakeOut">;

const columnHelper = createColumnHelper<StakeOut>();

const columns = [
  columnHelper.accessor("filed_date", {
    header: "Filed",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
  columnHelper.accessor("form_type", {
    header: "Form",
    cell: ({ row }) => (
      <span className="inline-flex items-center gap-1.5">
        <span className="font-medium">{row.original.form_type.replace("SCHEDULE ", "")}</span>
        {row.original.is_activist && (
          <Badge variant="destructive" className="font-normal">
            Activist
          </Badge>
        )}
      </span>
    ),
  }),
  columnHelper.display({
    id: "reporters",
    header: "Reporting persons",
    cell: ({ row }) => row.original.reporting_persons.map((p) => p.name).join(", "),
  }),
  columnHelper.accessor("percent_of_class", {
    header: "% of class",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue(), { signed: false })}</span>,
  }),
  columnHelper.accessor("is_current", {
    header: "Status",
    cell: ({ getValue }) => (getValue() ? "Current" : "Historical"),
  }),
  columnHelper.accessor("purpose_excerpt", {
    header: "Purpose",
    cell: ({ getValue }) => <span className="line-clamp-2 max-w-xs text-muted-foreground">{getValue() ?? "—"}</span>,
  }),
  columnHelper.display({
    id: "sec",
    header: "",
    cell: ({ row }) => <SecLink href={row.original.sec_url} label="SEC" />,
  }),
];

// See ledger Ruling F4.1.
const stakeColumns = columns as unknown as ColumnDef<StakeOut>[];

/** 13D/13G stake history, with 13D activist filings called out (spec 11, company page). */
export function StakesTab({ cik }: { cik: number }) {
  const query = useQuery({
    queryKey: ["company-stakes", cik],
    queryFn: async () => {
      const { data } = await api.GET("/api/companies/{cik}/stakes", { params: { path: { cik }, query: {} } });
      return data ?? [];
    },
  });

  if (query.status === "pending") return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  if (query.status === "error") {
    return (
      <ErrorState
        title="Stakes didn't load"
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
      columns={stakeColumns}
      data={query.data}
      getRowId={(s) => s.accession_no}
      empty={<EmptyState title="No 13D/13G stakes on record" />}
    />
  );
}
