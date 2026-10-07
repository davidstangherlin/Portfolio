// The filtering rules in web/tablefilter.js (docs/AS_BUILT.md §30), one
// check per fix from the review of filter_component.py. Run by
// tests/unit/test_table_filter.py (or directly: node tests/js/table_filter.test.js).
const assert = require("node:assert/strict");
const path = require("node:path");
const { tfNumber, tfApply, tfUpsert, tfReady } = require(path.join(__dirname, "..", "..", "web", "tablefilter.js"));

const pct = (v) => (v === null ? "n/a" : `${Math.round(v)}%`);
const fields = {
  code: { label: "Company", type: "text", get: (r) => r.code, text: (r) => `${r.code} ${r.name}` },
  sector: { label: "Sector", type: "text", get: (r) => r.sector },
  mos: { label: "Margin of safety", type: "num", get: (r) => r.mos, text: (r) => pct(r.mos) },
  cap: { label: "Market cap", type: "num", get: (r) => r.cap },
  note: { label: "Note", type: "text", get: (r) => r.note },
};
const rows = [
  { code: "BHP", name: "BHP Group", sector: "Basic Materials", mos: 23.4, cap: 2.1e11, note: "core, hold" },
  { code: "RIO", name: "Rio Tinto", sector: "Basic Materials", mos: 60, cap: 1.9e11, note: "" },
  { code: "CBA", name: "Commonwealth Bank", sector: "Financial Services", mos: -40, cap: 2.5e11, note: null },
  { code: "XYZ", name: "Block", sector: "Technology", mos: null, cap: 1.2e9, note: "watch" },
];
const run = (conditions, q = "") => tfApply(rows, { conditions, q }, fields).map((r) => r.code);
const c = (field, op, value, join = "AND", extra = {}) => ({ field, op, value, join, ...extra });

// Numbers typed as text: plain, %, $, thousands separators, k/m/b.
assert.equal(tfNumber("20"), 20);
assert.equal(tfNumber("20%"), 20);
assert.equal(tfNumber("-1.5"), -1.5);
assert.equal(tfNumber("$1,234.50"), 1234.5);
assert.equal(tfNumber("1.2B"), 1.2e9);
assert.equal(tfNumber("300k"), 300000);
assert.equal(tfNumber("abc"), null);
assert.deepEqual(run([c("mos", ">", "20%")]), ["BHP", "RIO"]);
assert.deepEqual(run([c("cap", "<", "$2B")]), ["XYZ"]);

// "=" on a number also matches the value as shown (23.4 is shown as 23%).
assert.deepEqual(run([c("mos", "=", "23")]), ["BHP"]);
assert.deepEqual(run([c("mos", "=", "60")]), ["RIO"]);

// "between" takes two values; either end may be left open.
assert.deepEqual(run([c("mos", "between", ["0", "50"])]), ["BHP"]);
assert.deepEqual(run([c("mos", "between", ["", "0"])]), ["CBA"]);
assert.equal(tfReady(c("mos", "between", ["", ""]), fields.mos), false);

// Comma-separated values are a list.
assert.deepEqual(run([c("code", "=", "bhp, cba")]), ["BHP", "CBA"]);
assert.deepEqual(run([c("code", "!=", "BHP,RIO")]), ["CBA", "XYZ"]);
assert.deepEqual(run([c("code", "contains", "tinto, block")]), ["RIO", "XYZ"]);

// Blank cells: "is empty" / "is not empty", for text and numbers alike.
assert.deepEqual(run([c("note", "is_empty")]), ["RIO", "CBA"]);
assert.deepEqual(run([c("mos", "is_not_empty")]), ["BHP", "RIO", "CBA"]);

// Top to bottom, no brackets: A AND B OR C is (A AND B) OR C.
assert.deepEqual(run([c("sector", "=", "Basic Materials"), c("mos", ">", "50"), c("code", "=", "CBA", "OR")]), ["RIO", "CBA"]);

// A condition still being typed is skipped, not applied as "matches nothing".
assert.deepEqual(run([c("mos", ">", "")]), ["BHP", "RIO", "CBA", "XYZ"]);
assert.deepEqual(run([c("mos", ">", "2o")]), ["BHP", "RIO", "CBA", "XYZ"]);

// Search looks at the text as shown, across every column.
assert.deepEqual(run([], "60%"), ["RIO"]);
assert.deepEqual(run([], "commonwealth"), ["CBA"]);
assert.deepEqual(run([c("sector", "=", "Basic Materials")], "hold"), ["BHP"]);

// "Show matching" / "Filter out": a value picked by right-click stays one value, commas and all.
const state = { conditions: [], q: "" };
tfUpsert(state, "note", "=", "core, hold", "core, hold");
assert.deepEqual(tfApply(rows, state, fields).map((r) => r.code), ["BHP"]);

// It replaces a lone AND condition on that column...
tfUpsert(state, "note", "!=", "core, hold");
assert.equal(state.conditions.length, 1);
assert.equal(state.conditions[0].op, "!=");
// ...but never rewrites an OR chain: it adds a condition instead.
const chain = { conditions: [c("sector", "=", "Technology"), c("code", "=", "BHP", "OR")], q: "" };
tfUpsert(chain, "code", "=", "RIO");
assert.equal(chain.conditions.length, 3);
assert.deepEqual(chain.conditions.map((x) => x.join), ["AND", "OR", "AND"]);

console.log("table filter: all checks pass");
