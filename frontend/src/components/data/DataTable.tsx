import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ArrowUpDown, Download } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const ROW_HEIGHT = 36;
const END_THRESHOLD_PX = 200;

interface DataTableProps<T> {
  // ColumnDef's 2nd generic (cell value type) defaults to `unknown`, same practical effect as
  // the plan's literal `ColumnDef<T, any>` without tripping `@typescript-eslint/no-explicit-any`.
  columns: ColumnDef<T>[];
  data: T[];
  getRowId: (row: T) => string;
  /** Present => infinite paging: fetch the next page. Also renders a "Load more" button, since
   * a short first page may never produce a scrollable container to detect on. */
  onEndReached?: () => void;
  isFetchingMore?: boolean;
  /** A link to the same query with `format=csv`, shown as an export link above the table. */
  csvHref?: string;
  empty?: ReactNode;
  height?: number;
  /** Controlled sort (e.g. the screener's server-side sort via the URL). Omit for the default
   * client-side sort of whatever rows are already loaded. */
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  manualSorting?: boolean;
}

/** A sticky-header, virtualized table. Sorts the loaded rows client-side by default; pass
 * `sorting`/`onSortingChange`/`manualSorting` to sort server-side instead (plan 07 Ruling P3). */
export function DataTable<T>({
  columns,
  data,
  getRowId,
  onEndReached,
  isFetchingMore,
  csvHref,
  empty,
  height = 480,
  sorting: controlledSorting,
  onSortingChange,
  manualSorting = false,
}: DataTableProps<T>) {
  const [internalSorting, setInternalSorting] = useState<SortingState>([]);
  const sorting = controlledSorting ?? internalSorting;
  const setSorting = onSortingChange ?? setInternalSorting;

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: manualSorting ? undefined : getSortedRowModel(),
    manualSorting,
    getRowId,
  });

  const rows = table.getRowModel().rows;
  const scrollRef = useRef<HTMLDivElement>(null);
  const calledForLength = useRef<number | null>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
    // jsdom (unit tests) never reports a real element size, so seed one: without it the
    // virtualizer measures a 0-height viewport and renders no rows at all.
    initialRect: { width: 0, height },
  });

  function handleScroll() {
    const el = scrollRef.current;
    if (!el || !onEndReached) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < END_THRESHOLD_PX;
    if (nearBottom && calledForLength.current !== rows.length) {
      calledForLength.current = rows.length;
      onEndReached();
    }
  }

  if (rows.length === 0 && empty) {
    return <div className="py-10 text-center text-sm text-muted-foreground">{empty}</div>;
  }

  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    virtualRows.length > 0 ? virtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;

  return (
    <div>
      {csvHref && (
        <div className="mb-2 flex justify-end">
          <a href={csvHref} className="inline-flex items-center gap-1 text-xs text-link hover:underline">
            <Download className="size-3.5" aria-hidden /> Export CSV
          </a>
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="overflow-auto rounded-md border border-border"
        style={{ height }}
      >
        <table className="w-full caption-bottom text-sm">
          <thead className="sticky top-0 z-10 bg-card">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-border">
                {headerGroup.headers.map((header) => {
                  const sortDir = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className="h-9 px-2 text-left align-middle font-medium whitespace-nowrap text-foreground"
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:text-foreground"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sortDir === "asc" ? (
                            <ArrowUp className="size-3.5" aria-hidden />
                          ) : sortDir === "desc" ? (
                            <ArrowDown className="size-3.5" aria-hidden />
                          ) : (
                            <ArrowUpDown className="size-3.5 opacity-40" aria-hidden />
                          )}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {paddingTop > 0 && (
              <tr aria-hidden="true">
                <td colSpan={columns.length} style={{ height: paddingTop }} />
              </tr>
            )}
            {virtualRows.map((virtualRow) => {
              const row = rows[virtualRow.index];
              return (
                <tr key={row.id} className={cn("border-b border-border hover:bg-muted/50")}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="p-2 align-middle whitespace-nowrap">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
            {paddingBottom > 0 && (
              <tr aria-hidden="true">
                <td colSpan={columns.length} style={{ height: paddingBottom }} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {onEndReached && (
        <div className="mt-2 flex justify-center">
          <button
            type="button"
            onClick={onEndReached}
            disabled={isFetchingMore}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {isFetchingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
