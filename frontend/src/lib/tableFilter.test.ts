// The table filter's rules (frontend/src/lib/tableFilter.ts), the same
// checks as tests/js/table_filter.test.js for web/tablefilter.js.
import { expect, it } from "vitest";
import { tfApply, tfNumber, tfReady, tfUpsert, type Condition, type Fields, type FilterState } from "./tableFilter";

interface Row { code: string; name: string; sector: string; mos: number | null; cap: number; note: string | null }
const expect_eq = (a: unknown, b: unknown) => expect(a).toEqual(b);

it("applies every rule the old filter did", () => {
  const pct = (v: number | null) => (v === null ? "n/a" : `${Math.round(v)}%`);
  const fields: Fields<Row> = {
    code: { label: "Company", type: "text", get: (r: Row) => r.code, text: (r: Row) => `${r.code} ${r.name}` },
    sector: { label: "Sector", type: "text", get: (r: Row) => r.sector },
    mos: { label: "Margin of safety", type: "num", get: (r: Row) => r.mos, text: (r: Row) => pct(r.mos) },
    cap: { label: "Market cap", type: "num", get: (r: Row) => r.cap },
    note: { label: "Note", type: "text", get: (r: Row) => r.note },
  };
  const rows: Row[] = [
    { code: "BHP", name: "BHP Group", sector: "Basic Materials", mos: 23.4, cap: 2.1e11, note: "core, hold" },
    { code: "RIO", name: "Rio Tinto", sector: "Basic Materials", mos: 60, cap: 1.9e11, note: "" },
    { code: "CBA", name: "Commonwealth Bank", sector: "Financial Services", mos: -40, cap: 2.5e11, note: null },
    { code: "XYZ", name: "Block", sector: "Technology", mos: null, cap: 1.2e9, note: "watch" },
  ];
  const run = (conditions: Condition[], q = "") => tfApply(rows, { conditions, q, open: false }, fields).map((r) => r.code);
  const c = (field: string, op: string, value: string | string[] | null = null, join: "AND" | "OR" = "AND"): Condition => ({ field, op, value, join });

  // Numbers typed as text: plain, %, $, thousands separators, k/m/b.
  expect_eq(tfNumber("20"), 20);
  expect_eq(tfNumber("20%"), 20);
  expect_eq(tfNumber("-1.5"), -1.5);
  expect_eq(tfNumber("$1,234.50"), 1234.5);
  expect_eq(tfNumber("1.2B"), 1.2e9);
  expect_eq(tfNumber("300k"), 300000);
  expect_eq(tfNumber("abc"), null);
  expect_eq(run([c("mos", ">", "20%")]), ["BHP", "RIO"]);
  expect_eq(run([c("cap", "<", "$2B")]), ["XYZ"]);

  // "=" on a number also matches the value as shown (23.4 is shown as 23%).
  expect_eq(run([c("mos", "=", "23")]), ["BHP"]);
  expect_eq(run([c("mos", "=", "60")]), ["RIO"]);

  // "between" takes two values; either end may be left open.
  expect_eq(run([c("mos", "between", ["0", "50"])]), ["BHP"]);
  expect_eq(run([c("mos", "between", ["", "0"])]), ["CBA"]);
  expect_eq(tfReady(c("mos", "between", ["", ""]), fields.mos), false);

  // Comma-separated values are a list.
  expect_eq(run([c("code", "=", "bhp, cba")]), ["BHP", "CBA"]);
  expect_eq(run([c("code", "!=", "BHP,RIO")]), ["CBA", "XYZ"]);
  expect_eq(run([c("code", "contains", "tinto, block")]), ["RIO", "XYZ"]);

  // Blank cells: "is empty" / "is not empty", for text and numbers alike.
  expect_eq(run([c("note", "is_empty")]), ["RIO", "CBA"]);
  expect_eq(run([c("mos", "is_not_empty")]), ["BHP", "RIO", "CBA"]);

  // Top to bottom, no brackets: A AND B OR C is (A AND B) OR C.
  expect_eq(run([c("sector", "=", "Basic Materials"), c("mos", ">", "50"), c("code", "=", "CBA", "OR")]), ["RIO", "CBA"]);

  // A condition still being typed is skipped, not applied as "matches nothing".
  expect_eq(run([c("mos", ">", "")]), ["BHP", "RIO", "CBA", "XYZ"]);
  expect_eq(run([c("mos", ">", "2o")]), ["BHP", "RIO", "CBA", "XYZ"]);

  // Search looks at the text as shown, across every column.
  expect_eq(run([], "60%"), ["RIO"]);
  expect_eq(run([], "commonwealth"), ["CBA"]);
  expect_eq(run([c("sector", "=", "Basic Materials")], "hold"), ["BHP"]);

  // "Show matching" / "Filter out": a value picked by right-click stays one value, commas and all.
  const state: FilterState = { conditions: [], q: "", open: false };
  tfUpsert(state, "note", "=", "core, hold", "core, hold");
  expect_eq(tfApply(rows, state, fields).map((r: Row) => r.code), ["BHP"]);

  // It replaces a lone AND condition on that column...
  tfUpsert(state, "note", "!=", "core, hold");
  expect_eq(state.conditions.length, 1);
  expect_eq(state.conditions[0].op, "!=");
  // ...but never rewrites an OR chain: it adds a condition instead.
  const chain: FilterState = { open: false, conditions: [c("sector", "=", "Technology"), c("code", "=", "BHP", "OR")], q: "" };
  tfUpsert(chain, "code", "=", "RIO");
  expect_eq(chain.conditions.length, 3);
  expect_eq(chain.conditions.map((x) => x.join), ["AND", "OR", "AND"]);
});
