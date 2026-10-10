// Table filters for Sift's list views (docs/AS_BUILT.md §30, ported from
// web/tablefilter.js): a search box over every column, a condition builder,
// removable chips, and right-click (press and hold on a phone) "Show
// matching" / "Filter out" on any cell. This file is the pure part: numbers
// typed as text compare as numbers ("20", "20%", "$1.2B"), "between" takes
// two values, comma-separated values are a list, a blank cell matches "is
// empty", and conditions apply top to bottom with no brackets: A AND B OR C
// means (A AND B) OR C. A condition still being typed is skipped.

export interface Field<R> { label: string; type: "text" | "num"; get: (r: R) => unknown; text?: (r: R) => string }
export type Fields<R> = Record<string, Field<R>>;
export interface Condition { field: string; op: string; value: string | string[] | null; join: "AND" | "OR"; shown?: string; exact?: boolean }
export interface FilterState { conditions: Condition[]; q: string; open: boolean }

export const TF_OPS = [
  { id: "=", label: "equals", chip: "=", types: ["text", "num"] },
  { id: "!=", label: "does not equal", chip: "≠", types: ["text", "num"] },
  { id: "contains", label: "contains", chip: "contains", types: ["text", "num"] },
  { id: "not_contains", label: "does not contain", chip: "doesn't contain", types: ["text", "num"] },
  { id: ">", label: "greater than", chip: ">", types: ["num"] },
  { id: "<", label: "less than", chip: "<", types: ["num"] },
  { id: "between", label: "between", chip: "between", types: ["num"] },
  { id: "is_empty", label: "is empty", chip: "is empty", types: ["text", "num"] },
  { id: "is_not_empty", label: "is not empty", chip: "is not empty", types: ["text", "num"] },
];
export const TF_NO_VALUE = new Set(["is_empty", "is_not_empty"]);
const TF_SCALE: Record<string, number> = { k: 1e3, m: 1e6, b: 1e9, t: 1e12 };

/* "20", "20%", "-1.5", "$1,234.50", "1.2B", "300k" as numbers; null if not a number. */
export function tfNumber(text: unknown): number | null {
  if (typeof text === "number") return Number.isFinite(text) ? text : null;
  if (text === null || text === undefined) return null;
  const m = String(text).trim().replace(/[,\s]/g, "").match(/^([+-]?)\$?([+-]?)(\d*\.?\d+)([kmbt]?)%?$/i);
  if (!m) return null;
  const sign = m[1] === "-" || m[2] === "-" ? -1 : 1;
  return sign * parseFloat(m[3]) * (m[4] ? TF_SCALE[m[4].toLowerCase()] : 1);
}
/* "BHP, RIO" as ["BHP", "RIO"]. */
export const tfTerms = (value: unknown): string[] => String(value ?? "").split(",").map((s) => s.trim()).filter(Boolean);
/* A value picked by right-click is one value even if it has a comma in it. */
const tfCondTerms = (c: Condition) => (c.exact ? [String(c.value ?? "")].filter((t) => t.trim()) : tfTerms(c.value));
export const tfBlank = (v: unknown) => v === null || v === undefined || String(v).trim() === "";
const tfLower = (v: unknown) => String(v ?? "").toLowerCase();
export const tfText = <R>(f: Field<R>, row: R): string => (f.text ? f.text(row) : String(f.get(row) ?? ""));

/* Whether a condition has what it needs to filter yet. */
export function tfReady<R>(c: Condition, f: Field<R> | undefined): boolean {
  if (!f) return false;
  if (TF_NO_VALUE.has(c.op)) return true;
  if (c.op === "between") {
    const [lo, hi] = Array.isArray(c.value) ? c.value : [];
    return tfNumber(lo) !== null || tfNumber(hi) !== null;
  }
  const terms = tfCondTerms(c);
  if (!terms.length) return false;
  if (f.type === "num" && [">", "<", "=", "!="].includes(c.op)) return terms.every((t) => tfNumber(t) !== null);
  return true;
}

function equalsNumber<R>(f: Field<R>, row: R, n: number | null): boolean {
  const v = f.get(row) as number | null | undefined;
  if (v === null || v === undefined || n === null) return false;
  if (Math.abs(v - n) <= 1e-9 * Math.max(1, Math.abs(n))) return true;
  return tfNumber(tfText(f, row)) === n;  // "23" matches a value shown as 23% but stored as 23.4
}

export function tfTest<R>(row: R, c: Condition, f: Field<R>): boolean {
  const v = f.get(row) as number | string | null | undefined;
  switch (c.op) {
    case "is_empty": return tfBlank(v);
    case "is_not_empty": return !tfBlank(v);
    case "contains":
    case "not_contains": {
      const text = tfLower(tfText(f, row));
      const hit = tfCondTerms(c).some((t) => text.includes(t.toLowerCase()));
      return c.op === "contains" ? hit : !hit;
    }
    case "=":
    case "!=": {
      const hit = f.type === "num"
        ? tfCondTerms(c).some((t) => equalsNumber(f, row, tfNumber(t)))
        : tfCondTerms(c).some((t) => tfLower(v).trim() === t.trim().toLowerCase());
      return c.op === "=" ? hit : !hit;
    }
    case ">": return v !== null && v !== undefined && (v as number) > (tfNumber(c.value) as number);
    case "<": return v !== null && v !== undefined && (v as number) < (tfNumber(c.value) as number);
    case "between": {
      if (v === null || v === undefined) return false;
      const [lo, hi] = (c.value as string[]).map(tfNumber);
      return (lo === null || (v as number) >= lo) && (hi === null || (v as number) <= hi);
    }
    default: return true;
  }
}

/* The rows that pass the conditions (top to bottom) and the search text. */
export function tfApply<R>(rows: R[], state: FilterState, fields: Fields<R>, extraSearch?: (r: R) => string): R[] {
  const conds = state.conditions.filter((c) => tfReady(c, fields[c.field]));
  const q = (state.q || "").trim().toLowerCase();
  if (!conds.length && !q) return rows;
  const keys = Object.keys(fields);
  return rows.filter((row) => {
    let ok: boolean | null = null;
    for (const c of conds) {
      const hit = tfTest(row, c, fields[c.field]);
      ok = ok === null ? hit : c.join === "OR" ? ok || hit : ok && hit;
    }
    if (ok === false) return false;
    if (!q) return true;
    const text = keys.map((k) => tfText(fields[k], row)).concat(extraSearch ? [extraSearch(row)] : []).join("  ").toLowerCase();
    return text.includes(q);
  });
}

/* "Show matching" / "Filter out": replace a lone AND condition on the
   column, otherwise add one, so an OR chain is never rewritten. */
export function tfUpsert(state: FilterState, field: string, op: string, value: string | null, shown?: string): void {
  const same = state.conditions.filter((c) => c.field === field);
  const cond: Condition = { field, op, value, shown, join: "AND", exact: true };
  if (same.length === 1 && (same[0].join === "AND" || state.conditions[0] === same[0])) {
    const i = state.conditions.indexOf(same[0]);
    cond.join = same[0].join;
    state.conditions[i] = cond;
  } else {
    state.conditions.push(cond);
  }
}

/* Each table keeps its own filters until the page reloads. */
const STATES: Record<string, FilterState> = {};
export const filterState = (key: string): FilterState => (STATES[key] ||= { conditions: [], q: "", open: false });
export const forgetFilters = (key: string): void => { delete STATES[key]; };
