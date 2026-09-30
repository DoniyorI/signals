import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { Link, useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { QuarterSelect } from "@/components/controls/QuarterSelect";
import { ChangeChip } from "@/components/data/ChangeChip";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { fmtPct, fmtShares, fmtUsd } from "@/lib/format";

type InstitutionRow = Schema<"InstitutionRow">;

const columnHelper = createColumnHelper<InstitutionRow>();

const columns = [
  columnHelper.display({
    id: "fund",
    header: "Institution",
    cell: ({ row }) => (
      <Link to={`/fund/${row.original.fund.cik}`} className="text-link hover:underline">
        {row.original.fund.name}
      </Link>
    ),
  }),
  columnHelper.display({
    id: "change",
    header: "Change",
    cell: ({ row }) => <ChangeChip change={row.original.change} />,
  }),
  columnHelper.accessor("shares", {
    header: "Shares",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtShares(getValue())}</span>,
  }),
  columnHelper.accessor("shares_change_pct", {
    header: "Shares change",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue())}</span>,
  }),
  columnHelper.accessor("value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("weight_in_fund", {
    header: "Weight in fund",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtPct(getValue(), { signed: false })}</span>,
  }),
  columnHelper.accessor("is_tracked", {
    header: "Tracked",
    cell: ({ getValue }) => (getValue() ? "Yes" : "No"),
  }),
];

// See ledger Ruling F4.1.
const institutionColumns = columns as unknown as ColumnDef<InstitutionRow>[];

/** 13F holders of this issuer for a chosen quarter, their quarter-over-quarter changes, and
 * totals (holders, new, exits) — spec 11, company page.
 *
 * Ledger Ruling F6.2: the totals row always renders both a `ChangeChip change="NEW"` and a
 * `ChangeChip change="EXIT"` next to their counts, even when a count is 0 — `InstitutionsOut`
 * only lists *current* holders in `rows` (exits are a count, `exit_count`, with no row detail;
 * unlike `FundHoldingsOut`, which does carry a separate `exits` array), so no single
 * company/period is guaranteed to have an EXIT-changed row to show inline. Reusing the same
 * chip vocabulary for the summary counts keeps both labels visible regardless of which
 * company/period is loaded — cost if wrong: purely cosmetic (plain-text counts instead of
 * chips), nothing else depends on this rendering choice. */
export function InstitutionsTab({ cik }: { cik: number }) {
  const [searchParams] = useSearchParams();
  const period = searchParams.get("period");

  const query = useQuery({
    queryKey: ["company-institutions", cik, period],
    queryFn: async () => {
      const { data } = await api.GET("/api/companies/{cik}/institutions", {
        params: { path: { cik }, query: { period: period ?? undefined } },
      });
      if (!data) throw new Error("Could not load institutional holders.");
      return data;
    },
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <QuarterSelect periods={query.data?.periods_available ?? []} />
        {query.data && (
          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <span>{query.data.holders_count} holders</span>
            <span className="inline-flex items-center gap-1.5">
              <ChangeChip change="NEW" /> {query.data.new_count}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <ChangeChip change="EXIT" /> {query.data.exit_count}
            </span>
          </div>
        )}
      </div>
      {query.status === "pending" ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : query.status === "error" ? (
        <ErrorState
          title="Institutions didn't load"
          action={
            <button type="button" onClick={() => query.refetch()} className="text-sm text-link hover:underline">
              Try again
            </button>
          }
        />
      ) : (
        <DataTable
          columns={institutionColumns}
          data={query.data.rows}
          getRowId={(r) => String(r.fund.cik)}
          empty={<EmptyState title="No institutional holders on record" />}
        />
      )}
    </div>
  );
}
