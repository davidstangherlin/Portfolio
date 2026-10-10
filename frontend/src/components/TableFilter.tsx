// One table's filter controls (tableFilter() in web/tablefilter.js): the
// search box, the pink "Filter" toggle with its condition builder, the
// chips, and the right-click (press and hold) menu on any cell. Each table
// keeps its own filters until the page reloads (filterState(key)).
import { useEffect, useReducer, useRef, type ReactElement, type MouseEvent as RMouseEvent, type TouchEvent as RTouchEvent } from "react";
import { h } from "../lib/dom";
import {
  filterState, TF_NO_VALUE, TF_OPS, tfApply, tfBlank, tfReady, tfText, tfUpsert, type Condition, type Field, type Fields,
} from "../lib/tableFilter";
import { HelpLink } from "./HelpLink";

const opOf = (id: string) => TF_OPS.find((o) => o.id === id)!;
const valueText = (c: Condition) => (c.op === "between"
  ? `${(c.value as string[])[0] || "…"} and ${(c.value as string[])[1] || "…"}` : TF_NO_VALUE.has(c.op) ? "" : (c.shown ?? c.value));

/* ---------- the right-click menu: one at a time, closed by clicking away, Escape, scrolling or a page change ---------- */
let menuEl: HTMLElement | null = null, menuOpenedAt = 0;
function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }
if (typeof document !== "undefined") {
  document.addEventListener("click", (e) => { if (menuEl && !menuEl.contains(e.target as Node)) closeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  window.addEventListener("scroll", closeMenu, { passive: true });
  window.addEventListener("hashchange", closeMenu);
}

export interface TableFilter<R> {
  apply: (rows: R[]) => R[];
  active: () => boolean;
  search: ReactElement; toggle: ReactElement; chips: ReactElement; builder: ReactElement;
  /* Props for the <table>: right-click or press and hold a cell. `columns[i]` is the
     field key of the i-th column (null: not filterable); `shown()` the rows as drawn. */
  tableProps: (columns: (string | null)[], shown: () => R[]) => {
    onContextMenu: (e: RMouseEvent<HTMLTableElement>) => void; onTouchStart: (e: RTouchEvent<HTMLTableElement>) => void;
    onTouchMove: () => void; onTouchEnd: () => void; onClickCapture: (e: RMouseEvent) => void;
  };
}

export function useTableFilter<R>(key: string, fields: Fields<R>, allRows: R[], onChange: () => void,
  { placeholder = "Search all columns", extraSearch }: { placeholder?: string; extraSearch?: (r: R) => string } = {}): TableFilter<R> {
  const state = filterState(key);
  const [, bump] = useReducer((x: number) => x + 1, 0);
  const keys = Object.keys(fields);
  const changed = () => { bump(); onChange(); };
  const focusLast = useRef(false);
  const builderRef = useRef<HTMLDivElement>(null);
  const long = useRef<{ timer: ReturnType<typeof setTimeout> | null; pressed: boolean }>({ timer: null, pressed: false });
  useEffect(() => {
    if (!focusLast.current) return;
    focusLast.current = false;
    const inputs = builderRef.current?.querySelectorAll<HTMLInputElement>(".tf-value");
    if (inputs && inputs.length) inputs[inputs.length - 1].focus();
  });

  const active = state.conditions.filter((c) => tfReady(c, fields[c.field])).length;
  const listId = (k: string) => `tf-${key.replace(/[^a-z0-9]/gi, "-")}-${k}`;
  const distinct = (fieldKey: string) => {
    const f = fields[fieldKey], seen = new Set<string>();
    for (const r of allRows) { const v = f.get(r); if (!tfBlank(v)) seen.add(String(v)); if (seen.size > 300) break; }
    return [...seen].sort((a, b) => a.localeCompare(b));
  };
  const removeAt = (i: number) => { state.conditions.splice(i, 1); changed(); };
  const clearAll = () => { state.conditions = []; changed(); };

  const search = <input type="search" className="tf-search" placeholder={placeholder} value={state.q} aria-label={placeholder}
    onChange={(e) => { state.q = e.target.value; changed(); }} />;
  const toggle = (
    <button type="button" className={`tf-toggle${active > 0 ? " on" : ""}`} aria-expanded={state.open} title="Filter by any column"
      onClick={() => { state.open = !state.open; bump(); }}>
      <span aria-hidden="true">☰ </span>Filter{active ? <span className="tf-n">{active}</span> : null}
    </button>
  );
  const chips = (
    <div className="tf-chips" role="group" aria-label="Active filters" hidden={!state.conditions.length || undefined}>
      {state.conditions.map((c, i) => {
        const f = fields[c.field], ready = tfReady(c, f);
        const label = `${i ? c.join + " " : ""}${f ? f.label : c.field} ${opOf(c.op).chip} ${valueText(c)}`.trim();
        return (
          <button key={i} type="button" className={`tf-chip${ready ? "" : " pending"}`} title={ready ? "Remove this filter" : "Not applied yet: finish it in the filter builder"}
            aria-label={`Remove filter: ${label}`} onClick={() => removeAt(i)}>{label}<span aria-hidden="true" className="x"> ✕</span></button>
        );
      })}
      {state.conditions.length ? <button type="button" className="link-btn tf-clear" onClick={clearAll}>Clear all</button> : null}
    </div>
  );

  const condRow = (c: Condition, i: number) => {
    const f = fields[c.field] || fields[keys[0]];
    const ops = TF_OPS.filter((o) => o.types.includes(f.type));
    const edited = () => { delete c.shown; delete c.exact; changed(); };
    const input = (value: string | null | undefined, onValue: (v: string) => void, label: string) => (
      <input className="tf-value" value={value ?? ""} aria-label={label} placeholder={f.type === "num" ? "e.g. 20" : "e.g. BHP, RIO"}
        list={f.type === "text" ? listId(c.field) : undefined} inputMode={f.type === "num" ? "decimal" : undefined}
        onChange={(e) => { onValue(e.target.value); edited(); }} />
    );
    const value = c.op === "between"
      ? <span className="tf-between">{input((c.value as string[])[0], (v) => { (c.value as string[])[0] = v; }, "From")} and {input((c.value as string[])[1], (v) => { (c.value as string[])[1] = v; }, "To")}</span>
      : TF_NO_VALUE.has(c.op) ? null : input((c.shown ?? c.value) as string, (v) => { c.value = v; }, "Value");
    return (
      <div className="tf-cond" key={i}>
        {i ? <select className="tf-join" aria-label="Join" value={c.join} onChange={(e) => { c.join = e.target.value as "AND" | "OR"; changed(); }}>
          {["AND", "OR"].map((j) => <option key={j} value={j}>{j}</option>)}</select> : <span className="tf-join where">Where</span>}
        <select aria-label="Column" value={c.field} onChange={(e) => {
          c.field = e.target.value; if (!opOf(c.op).types.includes(fields[c.field].type)) c.op = "=";
          if (c.op === "between" && !Array.isArray(c.value)) c.value = ["", ""];
          edited(); }}>
          {keys.map((k) => <option key={k} value={k}>{fields[k].label}</option>)}
        </select>
        <select aria-label="Condition" value={c.op} onChange={(e) => {
          const was = c.op; c.op = e.target.value;
          if (c.op === "between") c.value = ["", ""]; else if (was === "between") c.value = "";
          edited(); }}>
          {ops.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
        {value}
        <button type="button" className="icon-x" aria-label="Remove this condition" onClick={() => removeAt(i)}>✕</button>
      </div>
    );
  };
  const textKeys = [...new Set(state.conditions.map((c) => c.field).filter((k) => fields[k] && fields[k].type === "text"))];
  const builder = (
    <div className="tf-builder" ref={builderRef} hidden={!state.open || undefined}>
      {state.open ? (
        <>
          {state.conditions.map(condRow)}
          {textKeys.map((k) => <datalist key={k} id={listId(k)}>{distinct(k).map((v) => <option key={v} value={v} />)}</datalist>)}
          <div className="tf-actions">
            <button type="button" className="btn small" onClick={() => {
              state.conditions.push({ field: keys[0], op: fields[keys[0]].type === "num" ? ">" : "contains", value: "", join: "AND" });
              focusLast.current = true; changed(); }}>+ Add condition</button>
            {state.conditions.length ? <button type="button" className="btn small" onClick={clearAll}>Clear all</button> : null}
            <span className="hint">Applied top to bottom: A AND B OR C means (A AND B) OR C. Separate several values with commas. <HelpLink id="table-filters" /></span>
          </div>
        </>
      ) : null}
    </div>
  );

  const openMenu = (x: number, y: number, f: Field<R>, row: R) => {
    closeMenu();
    const v = f.get(row), shown = f.type === "num" ? tfText(f, row) : String(v ?? "");  // numbers as shown, text as matched
    const fieldKey = keys.find((k) => fields[k] === f) as string;
    const add = (op: string, value: string | null, label: string) => h("button", { type: "button", role: "menuitem", text: label, onclick: () => {
      tfUpsert(state, fieldKey, op, value, op === "between" || TF_NO_VALUE.has(op) ? undefined : shown);
      closeMenu(); changed();
    } });
    const value = f.type === "num" ? String(v) : String(v ?? "");
    const short = shown.length > 40 ? shown.slice(0, 39) + "…" : shown;
    const items = tfBlank(v)
      ? [add("is_empty", null, `Show only rows with no ${f.label}`), add("is_not_empty", null, `Hide rows with no ${f.label}`)]
      : [add("=", value, `Show matching: ${f.label} = ${short}`), add("!=", value, `Filter out: ${f.label} ≠ ${short}`),
        f.type === "num" ? add(">", value, `${f.label} greater than ${short}`) : null,
        f.type === "num" ? add("<", value, `${f.label} less than ${short}`) : null];
    menuEl = h("div", { class: "tf-menu", role: "menu", "aria-label": `Filter by ${f.label}` }, items.filter(Boolean));
    document.body.append(menuEl);
    const r = menuEl.getBoundingClientRect();
    menuEl.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`;
    menuEl.style.top = `${Math.max(8, y + r.height > innerHeight - 8 ? y - r.height : y)}px`;
    menuOpenedAt = Date.now();
    (menuEl.querySelector("button") as HTMLElement).focus();
  };

  const tableProps = (columns: (string | null)[], shownRows: () => R[]) => {
    const target = (el: Element, table: HTMLTableElement) => {
      const tr = el.closest("tr");
      if (!tr || !table.tBodies[0] || tr.parentElement !== table.tBodies[0]) return null;
      const td = el.closest("td");
      const k = td ? columns[td.cellIndex] : columns.find(Boolean);  // keyboard menu key on a row: first column
      const row = shownRows()[tr.sectionRowIndex];
      return k && fields[k] && row ? { f: fields[k], row } : null;
    };
    return {
      onContextMenu: (e: RMouseEvent<HTMLTableElement>) => {
        const t = target(e.target as Element, e.currentTarget);
        if (!t) return;
        e.preventDefault();
        if (Date.now() - menuOpenedAt < 700) return;  // a phone's long press already opened it
        const box = (e.target as Element).getBoundingClientRect();
        e.nativeEvent.stopPropagation();
        openMenu(e.clientX || box.left, e.clientY || box.bottom, t.f, t.row);
      },
      onTouchStart: (e: RTouchEvent<HTMLTableElement>) => {
        const t = target(e.target as Element, e.currentTarget);
        if (!t || e.touches.length !== 1) return;
        const { clientX, clientY } = e.touches[0];
        long.current.pressed = false;
        long.current.timer = setTimeout(() => { long.current.pressed = true; openMenu(clientX, clientY, t.f, t.row); }, 550);
      },
      onTouchMove: () => { if (long.current.timer) clearTimeout(long.current.timer); long.current.timer = null; },
      onTouchEnd: () => { if (long.current.timer) clearTimeout(long.current.timer); long.current.timer = null; },
      onClickCapture: (e: RMouseEvent) => {  // the tap that ends a long press doesn't open the row
        if (long.current.pressed) { e.preventDefault(); e.stopPropagation(); long.current.pressed = false; }
      },
    };
  };

  return {
    apply: (rows) => tfApply(rows, state, fields, extraSearch),
    active: () => !!state.q.trim() || state.conditions.some((c) => tfReady(c, fields[c.field])),
    search, toggle, chips, builder, tableProps,
  };
}
