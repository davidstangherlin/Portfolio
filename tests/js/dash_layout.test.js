// The dashboard layout's ordering rules in web/dashlayout.js (docs/AS_BUILT.md §20).
// Run by tests/unit/test_dash_layout.py (or directly: node tests/js/dash_layout.test.js).
const assert = require("node:assert/strict");
const path = require("node:path");
const { dlMerge, dlArrange } = require(path.join(__dirname, "..", "..", "web", "dashlayout.js"));

const defaults = ["attention", "changes", "movers", "top", "etfs"];

// Nothing saved: the default order, nothing hidden, default widths.
assert.deepEqual(dlArrange(null, defaults).map((e) => [e.id, e.hidden, e.wide]),
  defaults.map((id) => [id, false, null]));

// A saved order wins; a widget added to Sift since takes its default place
// (straight after the widget before it by default); one Sift dropped is ignored.
const saved = { cards: [{ id: "top", hidden: false, wide: true }, { id: "attention", hidden: true, wide: null },
  { id: "changes", hidden: false, wide: null }, { id: "gone", hidden: false, wide: null }, { id: "etfs", hidden: false, wide: false }] };
assert.deepEqual(dlArrange(saved, defaults).map((e) => e.id), ["top", "attention", "changes", "movers", "etfs"]);
assert.equal(dlArrange(saved, defaults).find((e) => e.id === "attention").hidden, true);
assert.equal(dlArrange(saved, defaults).find((e) => e.id === "top").wide, true);

// A new first widget goes first.
assert.deepEqual(dlMerge(["b", "c"], ["a", "b", "c"]), ["a", "b", "c"]);
// After a drag, a widget not on show (hidden, or nothing to show today) stays
// just after the widget it followed: b after a, d after c.
assert.deepEqual(dlMerge(["c", "a"], ["a", "b", "c", "d"]), ["c", "d", "a", "b"]);
// Duplicates keep their first place.
assert.deepEqual(dlMerge(["a", "b", "a"], ["a", "b"]), ["a", "b"]);

console.log("all checks pass");
