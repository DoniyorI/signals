import type { ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";
import type { Schema } from "@/api/client";
import { DataTable } from "@/components/data/DataTable";
import { CoverageRatingPill } from "@/components/data/CoverageRatingPill";
import { ReturnCell } from "@/components/data/ReturnCell";
import { EmptyState } from "@/components/state/EmptyState";
import { fmtDate } from "@/lib/format";
import type { ScreenerTableControls } from "../ScreenerPage";

type Row = Schema<"InsiderScreenRow">;
export function InsiderScreener({ data, window, ...controls }: ScreenerTableControls & { data: Row[] }) {
  const columns: ColumnDef<Row>[] = [
    { id: "owner", accessorFn: (r) => r.owner.name, header: "Insider", cell: ({ row: { original: r } }) => <Link className="text-link" to={`/insider/${r.owner.cik}`}>{r.owner.name}</Link> },
    { id: "issuer", accessorFn: (r) => r.primary_issuer?.ticker ?? r.primary_issuer?.name, header: "Company", cell: ({ row: { original: r } }) => r.primary_issuer ? <Link className="text-link" to={`/company/${r.primary_issuer.cik}`}>{r.primary_issuer.ticker ?? r.primary_issuer.name}</Link> : "—" },
    { accessorKey: "roles", header: "Roles", cell: ({ row }) => row.original.roles.join(", ") || "—" },
    { accessorKey: "sector", header: "Sector" },
    { id: "rating", accessorFn: (r) => r.rating.score, header: "Rating", sortDescFirst: true, cell: ({ row }) => <CoverageRatingPill rating={row.original.rating} compact /> },
    { accessorKey: "avg_roi_6m", header: "Avg ROI", sortDescFirst: true, cell: ({ row }) => <ReturnCell value={row.original.avg_roi_6m} /> },
    { accessorKey: "hit_rate", header: "Hit rate", sortDescFirst: true, cell: ({ row }) => <ReturnCell value={row.original.hit_rate} /> },
    { accessorKey: "n_decisions", header: "Decisions", sortDescFirst: true },
    { accessorKey: "last_trade_date", header: "Last trade", sortDescFirst: true, cell: ({ row }) => fmtDate(row.original.last_trade_date) },
    { id: "return", accessorFn: (r) => r.windows[window], header: `${window.toUpperCase()} return`, sortDescFirst: true, cell: ({ row }) => <ReturnCell value={row.original.windows[window]} /> },
    { accessorKey: "risk_label", header: "Risk" },
  ];
  return <DataTable columns={columns} data={data} getRowId={(r) => String(r.owner.cik)} manualSorting {...controls}
    empty={<EmptyState title="No insiders match these filters" />} />;
}
