import { useState, type ReactNode } from "react";

/** What a column sorts by; null always sorts last, whichever the direction. */
export type SortValue = string | number | null;

export interface Column<Row> {
  key: string;
  header: string;
  cell: (row: Row) => ReactNode;
  align?: "left" | "right" | undefined;
  /** Makes the header a sort button. */
  sortValue?: ((row: Row) => SortValue) | undefined;
}

interface DataTableProps<Row> {
  caption: string;
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string | number;
  onRowClick?: (row: Row) => void;
}

interface Sort {
  key: string;
  descending: boolean;
}

function compare(a: SortValue, b: SortValue, descending: boolean): number {
  if (a === null || b === null) return Number(a === null) - Number(b === null);
  const order =
    typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
  return descending ? -order : order;
}

/**
 * Sorts a copy of the rows by one column; ties keep the caller's order, so the page's own
 * ordering (most urgent first, newest first) is the default and the tie-breaker.
 */
function sortRows<Row>(
  rows: readonly Row[],
  columns: readonly Column<Row>[],
  sort: Sort | null,
): readonly Row[] {
  const sortValue = columns.find((column) => column.key === sort?.key)?.sortValue;
  if (sort === null || sortValue === undefined) return rows;
  return rows
    .map((row, index) => ({ row, index, value: sortValue(row) }))
    .sort((a, b) => compare(a.value, b.value, sort.descending) || a.index - b.index)
    .map((entry) => entry.row);
}

/** Ascending, then descending, then back to the page's own order. */
function nextSort(current: Sort | null, key: string): Sort | null {
  if (current?.key !== key) return { key, descending: false };
  return current.descending ? null : { key, descending: true };
}

function SortIcon({ direction }: { direction: "ascending" | "descending" | "none" }) {
  const glyph = { ascending: "▲", descending: "▼", none: "↕" }[direction];
  return (
    <span aria-hidden="true" className={direction === "none" ? "opacity-40" : ""}>
      {glyph}
    </span>
  );
}

/**
 * One table for every list in the three portals; the caption is read by screen readers. A wide
 * table scrolls sideways on a narrow screen, so its frame takes keyboard focus (P5.6, WCAG 2.1.1).
 * Columns with a sortValue sort on a click of their header, which reports aria-sort.
 */
export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  onRowClick,
}: DataTableProps<Row>) {
  const [sort, setSort] = useState<Sort | null>(null);
  const shown = sortRows(rows, columns, sort);
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className="overflow-x-auto rounded-lg border border-line bg-surface focus-visible:outline-2 focus-visible:outline-accent"
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line bg-raised text-left text-xs tracking-wide text-muted uppercase">
            {columns.map((column) => {
              const direction =
                sort?.key !== column.key ? "none" : sort.descending ? "descending" : "ascending";
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={column.sortValue === undefined ? undefined : direction}
                  className={`px-3 py-2 font-semibold ${column.align === "right" ? "text-right" : ""}`}
                >
                  {column.sortValue === undefined ? (
                    column.header
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setSort((current) => nextSort(current, column.key));
                      }}
                      className={`inline-flex items-center gap-1 rounded uppercase hover:text-ink focus-visible:outline-2 focus-visible:outline-accent ${direction === "none" ? "" : "text-ink"}`}
                    >
                      {column.header}
                      <SortIcon direction={direction} />
                    </button>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr
              key={rowKey(row)}
              className={`border-b border-line last:border-0 ${onRowClick ? "cursor-pointer hover:bg-raised" : ""}`}
              onClick={
                onRowClick
                  ? () => {
                      onRowClick(row);
                    }
                  : undefined
              }
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-3 py-2 align-middle ${column.align === "right" ? "text-right" : ""}`}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
