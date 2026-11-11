import type { ReactNode } from "react";

export interface Column<Row> {
  key: string;
  header: string;
  cell: (row: Row) => ReactNode;
  align?: "left" | "right" | undefined;
}

interface DataTableProps<Row> {
  caption: string;
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string | number;
  onRowClick?: (row: Row) => void;
}

/** One table for every list in the three portals; the caption is read by screen readers. */
export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  onRowClick,
}: DataTableProps<Row>) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line bg-raised text-left text-xs tracking-wide text-muted uppercase">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`px-3 py-2 font-semibold ${column.align === "right" ? "text-right" : ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
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
