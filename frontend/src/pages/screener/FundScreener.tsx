import type { ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";
import type { Schema } from "@/api/client";
import { DataTable } from "@/components/data/DataTable";
import { RatingPill } from "@/components/data/RatingPill";
import { ReturnCell } from "@/components/data/ReturnCell";
import { EmptyState } from "@/components/state/EmptyState";
import { fmtUsd, fmtPct } from "@/lib/format";
import type { ScreenerTableControls } from "../ScreenerPage";

type Row = Schema<"FundScreenRow">;
export function FundScreener({ data, window, ...controls }: ScreenerTableControls & { data: Row[] }) {
  const columns: ColumnDef<Row>[] = [
    { id: "fund", accessorFn: (r) => r.fund.name, header: "Fund", cell: ({ row }) => <Link className="text-link" to={`/fund/${row.original.fund.cik}`}>{row.original.fund.name}</Link> },
    { accessorKey: "latest_value_usd", header: "Portfolio value", cell: ({ row }) => fmtUsd(row.original.latest_value_usd) },
    { accessorKey: "positions", header: "Positions" },
    { accessorKey: "top_sector", header: "Top sector" },
    { id: "rating", accessorFn: (r) => r.rating.score, header: "Rating (quarterly)", sortDescFirst: true, cell: ({ row }) => <RatingPill rating={row.original.rating} /> },
    { id: "return", accessorFn: (r) => r.windows[window], header: `${window.toUpperCase()} return`, sortDescFirst: true, cell: ({ row }) => <ReturnCell value={row.original.windows[window]} /> },
    { accessorKey: "risk_label", header: "Risk" },
    { accessorKey: "coverage_pct", header: "Coverage", cell: ({ row }) => fmtPct(row.original.coverage_pct) },
  ];
  return <DataTable columns={columns} data={data} getRowId={(r) => String(r.fund.cik)} manualSorting {...controls}
    empty={<EmptyState title="No funds match these filters" />} />;
}
