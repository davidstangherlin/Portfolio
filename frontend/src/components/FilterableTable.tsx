// A whole filterable table for pages that draw a table once (watchlists,
// portfolios): the controls, then `render(rows)`'s table, redrawn on every
// change (filterableTable() in web/tablefilter.js). `columns` lists each
// column's field key in order (null: not filterable).
import { useReducer, type ReactNode } from "react";
import type { Fields } from "../lib/tableFilter";
import { useTableFilter, type TableFilter } from "./TableFilter";

export function FilterableTable<R>({ filterKey, fields, columns, rows, render }: {
  filterKey: string; fields: Fields<R>; columns: (string | null)[]; rows: R[];
  render: (shown: R[], tableProps: ReturnType<TableFilter<R>["tableProps"]>) => ReactNode;
}) {
  const [, bump] = useReducer((x: number) => x + 1, 0);
  const tf = useTableFilter(filterKey, fields, rows, bump);
  const shown = tf.apply(rows);
  const active = tf.active();
  return (
    <div className="tf-wrap">
      <div className="controls tf-controls" hidden={(rows.length < 2 && !active) || undefined}>
        {tf.search}{tf.toggle}<span className="count">{active ? `${shown.length} of ${rows.length}` : ""}</span>
      </div>
      {tf.chips}{tf.builder}
      <div>
        {render(shown, tf.tableProps(columns, () => shown))}
        {!shown.length && rows.length ? <p className="hint tf-none">No rows match these filters.</p> : null}
      </div>
    </div>
  );
}
