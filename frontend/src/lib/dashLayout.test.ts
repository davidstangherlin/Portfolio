// The same checks as tests/js/dash_layout.test.js, for the TypeScript port.
import { expect, it } from "vitest";
import { dlArrange, dlMerge, type Layout } from "./dashLayout";

const defaults = ["attention", "changes", "movers", "top", "etfs"];

it("keeps the saved order and puts new widgets in their default place", () => {
  expect(dlArrange(null, defaults).map((e) => [e.id, e.hidden, e.wide])).toEqual(defaults.map((id) => [id, false, null]));
  const saved: Layout = { cards: [{ id: "top", hidden: false, wide: true }, { id: "attention", hidden: true, wide: null },
    { id: "changes", hidden: false, wide: null }, { id: "gone", hidden: false, wide: null }, { id: "etfs", hidden: false, wide: false }] };
  expect(dlArrange(saved, defaults).map((e) => e.id)).toEqual(["top", "attention", "changes", "movers", "etfs"]);
  expect(dlArrange(saved, defaults).find((e) => e.id === "attention")!.hidden).toBe(true);
  expect(dlArrange(saved, defaults).find((e) => e.id === "top")!.wide).toBe(true);
  expect(dlMerge(["b", "c"], ["a", "b", "c"])).toEqual(["a", "b", "c"]);
  expect(dlMerge(["c", "a"], ["a", "b", "c", "d"])).toEqual(["c", "d", "a", "b"]);
  expect(dlMerge(["a", "b", "a"], ["a", "b"])).toEqual(["a", "b"]);
});
