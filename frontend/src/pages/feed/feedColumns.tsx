import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";
import type { Schema } from "@/api/client";
import { BadgeChip } from "@/components/data/BadgeChip";
import { PlanChip } from "@/components/data/PlanChip";
import { SecLink } from "@/components/data/SecLink";
import { fmtDateET, fmtRelative, fmtShares, fmtUsd } from "@/lib/format";

type FeedItem = Schema<"FeedItemOut">;

/** `/company/<ticker or cik>` — the ticker when known, else the CIK (plan 07, F4). */
export function companyHref(issuer: Schema<"IssuerRef">): string {
  return `/company/${issuer.ticker ?? issuer.cik}`;
}

/** 13F rows' owners are funds; every other form's owners are insiders. */
export function isFundRow(formType: string): boolean {
  return formType.startsWith("13F");
}

export function ownerHref(cik: number, formType: string): string {
  return isFundRow(formType) ? `/fund/${cik}` : `/insider/${cik}`;
}

const columnHelper = createColumnHelper<FeedItem>();

/** Shared with the watchlist activity feed (F10), which also renders `FeedItemOut` rows. */
const columns = [
  columnHelper.accessor("accepted_at", {
    id: "time",
    header: "Time",
    cell: ({ getValue }) => {
      const acceptedAt = getValue();
      return (
        <span className="text-muted-foreground" title={acceptedAt ? fmtDateET(acceptedAt) : undefined}>
          {acceptedAt ? fmtRelative(acceptedAt) : "—"}
        </span>
      );
    },
  }),
  columnHelper.accessor("form_type", {
    header: "Form",
    cell: ({ getValue }) => <span className="font-medium">{getValue()}</span>,
  }),
  columnHelper.display({
    id: "company",
    header: "Company",
    cell: ({ row }) => {
      const issuer = row.original.issuer;
      if (!issuer) return <span className="text-muted-foreground">—</span>;
      return (
        <Link to={companyHref(issuer)} className="text-link hover:underline">
          {issuer.ticker ?? issuer.name}
        </Link>
      );
    },
  }),
  columnHelper.display({
    id: "owners",
    header: "Owners",
    cell: ({ row }) => {
      const item = row.original;
      return (
        <span>
          {item.owners.map((owner, i) => (
            <span key={owner.cik}>
              <Link to={ownerHref(owner.cik, item.form_type)} className="text-link hover:underline">
                {owner.name}
              </Link>
              {i < item.owners.length - 1 ? "; " : ""}
            </span>
          ))}
        </span>
      );
    },
  }),
  columnHelper.accessor("top_role", {
    header: "Role",
    cell: ({ getValue }) => getValue() ?? <span className="text-muted-foreground">—</span>,
  }),
  columnHelper.accessor("direction", {
    header: "Direction",
    cell: ({ getValue }) => {
      const dir = getValue();
      return dir ? dir[0].toUpperCase() + dir.slice(1) : <span className="text-muted-foreground">—</span>;
    },
  }),
  columnHelper.accessor("value_usd", {
    header: "Value",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
  }),
  columnHelper.accessor("shares", {
    header: "Shares",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtShares(getValue())}</span>,
  }),
  columnHelper.accessor("price", {
    header: "Price",
    cell: ({ getValue }) => <span className="tabular-nums">{fmtUsd(getValue())}</span>,
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
  columnHelper.display({
    id: "sec",
    header: "",
    cell: ({ row }) => <SecLink href={row.original.sec_url} label="SEC" />,
  }),
];

// `createColumnHelper` infers each column's own value type (string, number | null, …), so the
// array is really a union of differently-parameterized `ColumnDef<FeedItem, X>`s. DataTable's
// prop type erases that to `ColumnDef<FeedItem>` (TValue defaults to `unknown`) so it can take
// any page's columns; going through `unknown` sidesteps a TanStack Table generic-variance
// false positive on that erasure (confirmed harmless: every cell/header here is a plain
// function of `row.original`, never of the erased TValue itself).
export const feedColumns = columns as unknown as ColumnDef<FeedItem>[];
