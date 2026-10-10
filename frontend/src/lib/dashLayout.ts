// The dashboard layout's ordering rules (docs/AS_BUILT.md §20, ported from
// web/dashlayout.js): your widget order, hidden widgets and widths.

export interface LayoutEntry { id: string; hidden: boolean; wide: boolean | null }
export interface Layout { cards: LayoutEntry[] }

/* `primary` in its own order, then each id of `reference` it lacks, placed
   straight after the nearest id before it in `reference` (or first). Keeps
   new widgets, and ones not shown today, where they belong. */
export function dlMerge(primary: string[], reference: string[]): string[] {
  const out = [...new Set(primary)];
  reference.forEach((id, i) => {
    if (out.includes(id)) return;
    let at = 0;
    for (let j = i - 1; j >= 0; j--) {
      const k = out.indexOf(reference[j]);
      if (k >= 0) { at = k + 1; break; }
    }
    out.splice(at, 0, id);
  });
  return out;
}

/* One entry per known widget, in the saved order (widgets Sift no longer
   has are dropped; new ones take their default place). */
export function dlArrange(saved: Layout | null | undefined, defaults: string[]): LayoutEntry[] {
  const byId = new Map<string, LayoutEntry>();
  for (const c of (saved && saved.cards) || []) if (defaults.includes(c.id) && !byId.has(c.id)) byId.set(c.id, c);
  return dlMerge([...byId.keys()], defaults).map((id) => ({ hidden: false, wide: null, ...(byId.get(id) || {}), id }));
}
