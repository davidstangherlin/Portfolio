// A sortable column heading with its explanation (the screener and fund
// lists): click or Enter sorts, aria-sort says how.
import type { ReactNode } from "react";
import { useFieldHelp } from "./FieldHelp";

export interface Sort { key: string; dir: "asc" | "desc" }

export function SortTh({ label, sortKey, sort, onSort, className, children }:
  { label: string; sortKey: string; sort: Sort; onSort: () => void; className?: string; children?: ReactNode }) {
  const { props, info } = useFieldHelp(label);
  const cls = [className, (props as { className?: string }).className].filter(Boolean).join(" ") || undefined;
  return (
    <th {...props} className={cls} data-sort={sortKey} scope="col" tabIndex={0}
      aria-sort={sortKey === sort.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      onClick={onSort} onKeyDown={(e) => { if (e.key === "Enter") onSort(); }}>
      {children ?? label}{info}
    </th>
  );
}

/* Sort rows by a value, missing values last, ties broken by `tie` (larger first). */
export function sortRows<R>(rows: R[], value: (r: R) => unknown, dir: "asc" | "desc", tie: (r: R) => number): R[] {
  const d = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = value(a) as number | string | null | undefined, vb = value(b) as number | string | null | undefined;
    if (va === null || va === undefined) return vb === null || vb === undefined ? tie(b) - tie(a) : 1;
    if (vb === null || vb === undefined) return -1;
    const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number);
    return cmp ? cmp * d : tie(b) - tie(a);
  });
}
