import { useInfiniteQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { api, type Schema } from "@/api/client";
import { DataTable } from "@/components/data/DataTable";
import { PlanChip } from "@/components/data/PlanChip";
import { SecLink } from "@/components/data/SecLink";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { Switch } from "@/components/ui/switch";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtDate, fmtShares, fmtUsd } from "@/lib/format";

type TransactionOut = Schema<"TransactionOut">;

const columnHelper = createColumnHelper<TransactionOut>();

const columns = [
  columnHelper.accessor("transaction_date", {
    header: "Date",
    cell: ({ getValue }) => fmtDate(getValue()),
  }),
  columnHelper.accessor("form_type", { header: "Form" }),
  columnHelper.accessor("code_label", {
    header: "Type",
    cell: ({ row }) => row.original.code_label ?? row.original.code ?? "—",
  }),
  columnHelper.accessor("acquired_disposed", {
    header: "A/D",
    cell: ({ getValue }) => getValue() ?? "—",
  }),
  columnHelper.accessor("shares", {
    header: "Shares",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtShares(getValue())}</span>,
  }),
  columnHelper.accessor("price", {
    header: "Price",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("shares_owned_after", {
    header: "Owned after",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtShares(getValue())}</span>,
  }),
  columnHelper.accessor("security_title", { header: "Security" }),
  columnHelper.display({
    id: "plan",
    header: "Plan",
    cell: ({ row }) => <PlanChip flag={row.original.plan_10b5_1} />,
  }),
  columnHelper.accessor("superseded", {
    header: "",
    cell: ({ getValue }) => (getValue() ? <span className="text-xs text-muted-foreground">Superseded</span> : null),
  }),
  columnHelper.display({
    id: "sec",
    header: "",
    cell: ({ row }) => <SecLink href={row.original.sec_url} label="SEC" />,
  }),
];

// See ledger Ruling F4.1.
const transactionColumns = columns as unknown as ColumnDef<TransactionOut>[];

function rowKey(t: TransactionOut): string {
  return `${t.accession_no}-${t.transaction_date}-${t.code}-${t.shares}-${t.price}`;
}

/** The full transaction log: every code, an SEC link per row, and a toggle to reveal
 * superseded rows (spec 11, insider profile). */
export function TransactionsTab({ cik }: { cik: number }) {
  const [showSuperseded, setShowSuperseded] = useUrlState<boolean>(
    "show_superseded",
    false,
    (raw) => raw === "true",
    (v) => (v ? "true" : null),
  );

  const query = useInfiniteQuery({
    queryKey: ["insider-transactions", cik, showSuperseded],
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const { data } = await api.GET("/api/insiders/{cik}/transactions", {
        params: { path: { cik }, query: { include_superseded: showSuperseded, cursor: pageParam, limit: 50 } },
      });
      if (!data) throw new Error("Could not load transactions.");
      return data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  return (
    <div className="flex flex-col gap-3">
      <label className="inline-flex w-fit items-center gap-2 text-sm text-muted-foreground">
        <Switch checked={showSuperseded} onCheckedChange={setShowSuperseded} aria-label="Show superseded transactions" />
        Show superseded
      </label>
      {query.status === "pending" ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : query.status === "error" ? (
        <ErrorState
          title="Transactions didn't load"
          action={
            <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
              Try again
            </button>
          }
        />
      ) : (
        <DataTable
          columns={transactionColumns}
          data={query.data.pages.flatMap((page) => page.items)}
          getRowId={rowKey}
          onEndReached={query.hasNextPage ? () => query.fetchNextPage() : undefined}
          isFetchingMore={query.isFetchingNextPage}
          empty={<EmptyState title="No transactions" />}
        />
      )}
    </div>
  );
}
