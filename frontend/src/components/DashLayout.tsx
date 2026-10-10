// The dashboard's widgets, arranged (dashboardLayout() in web/dashlayout.js):
// your order, hidden widgets and widths, saved in Sift's database so every
// browser shows the same. Every widget starts pinned; its pin unlocks it to
// drag by its title bar (mouse or finger), move with the arrows, switch
// between half and full width, or hide.
import { useLayoutEffect, useRef, useState, type PointerEvent as RPointerEvent, type ReactElement } from "react";
import { send } from "../lib/api";
import { dlArrange, dlMerge, type Layout, type LayoutEntry } from "../lib/dashLayout";
import { showMessage } from "../lib/forms";
import { DashCardContext } from "./Card";

export interface WidgetSpec { id: string; title: string; card: ReactElement | null; defaultWide: boolean }

const PinIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1={12} x2={12} y1={17} y2={22} />
    <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" />
  </svg>
);

export function DashLayout({ specs, saved, onSaved }: { specs: WidgetSpec[]; saved: Layout | null; onSaved: (l: Layout | null) => void }) {
  const defaults = specs.map((x) => x.id);
  const title = (id: string) => specs.find((x) => x.id === id)!.title;
  const [entries, setEntries] = useState<LayoutEntry[]>(() => dlArrange(saved, defaults));
  const [unlocked, setUnlocked] = useState<Set<string>>(new Set());
  const [dragOrder, setDragOrder] = useState<string[] | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [layout, setLayout] = useState<Layout | null>(saved);
  const grid = useRef<HTMLDivElement>(null), msg = useRef<HTMLSpanElement>(null);
  const saving = useRef<Promise<unknown>>(Promise.resolve());
  const keepTop = useRef<{ id: string; top: number } | null>(null);
  const focusAfter = useRef<{ id: string; sel: string } | null>(null);
  const has = new Set(specs.filter((x) => x.card).map((x) => x.id));

  const save = (next: LayoutEntry[]) => {
    const next_: Layout = { cards: next.map(({ id, hidden, wide }) => ({ id, hidden, wide })) };
    setLayout(next_); onSaved(next_);
    saving.current = saving.current.then(() => send("PUT", "/api/dashboard/layout", next_))
      .then(() => { if (msg.current) msg.current.textContent = ""; })
      .catch((err) => showMessage(msg.current, `Layout not saved: ${(err as Error).message}`, false));
  };
  const update = (next: LayoutEntry[]) => { setEntries(next); save(next); };
  const shownIds = () => (dragOrder ?? entries.filter((e) => !e.hidden && has.has(e.id)).map((e) => e.id));
  const reorder = (visible: string[]) => {
    const ids = dlMerge(visible, entries.map((e) => e.id));
    return ids.map((id) => entries.find((e) => e.id === id)!);
  };
  const move = (id: string, step: number) => {
    const ids = shownIds(), i = ids.indexOf(id), j = i + step;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    focusAfter.current = { id, sel: step < 0 ? ".dl-up" : ".dl-down" };
    update(reorder(ids));
  };

  const drag = (e: RPointerEvent, id: string) => {
    if (!unlocked.has(id) || e.button > 0 || (e.target as Element).closest("button, a, input, select")) return;
    e.preventDefault();
    // Followed on the window, not the title bar: moving the widget in the page
    // ends the browser's capture of the pointer, which would stop the drag.
    const pointer = e.pointerId, before = shownIds();
    let order = [...before];
    setDragging(id);
    document.documentElement.classList.add("dl-drag-on");
    const el = () => grid.current?.querySelector<HTMLElement>(`[data-card="${id}"]`);
    const onMove = (ev: PointerEvent) => {
      if (ev.pointerId !== pointer) return;
      const over = document.elementsFromPoint(ev.clientX, ev.clientY)
        .map((x) => x.closest && x.closest<HTMLElement>(".cards.dash > .card")).find((c) => c && c.dataset.card !== id);
      if (over && over.dataset.card) {
        const from = order.indexOf(id), to = order.indexOf(over.dataset.card);
        const next = order.filter((x) => x !== id);
        next.splice(to > from ? next.indexOf(over.dataset.card) + 1 : next.indexOf(over.dataset.card), 0, id);
        if (next.join() !== order.join()) {
          order = next;
          keepTop.current = { id, top: el()?.getBoundingClientRect().top ?? 0 };  // keep it under the pointer: the page moves, not the widget
          setDragOrder(next);
        }
      }
      if (ev.clientY < 70) scrollBy(0, -14); else if (ev.clientY > innerHeight - 50) scrollBy(0, 14);
    };
    const onUp = (ev: PointerEvent) => {
      if (ev.pointerId !== pointer) return;
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerup", onUp);
      removeEventListener("pointercancel", onUp);
      setDragging(null); setDragOrder(null);
      document.documentElement.classList.remove("dl-drag-on");
      if (order.join() !== before.join()) update(reorder(order));
    };
    addEventListener("pointermove", onMove);
    addEventListener("pointerup", onUp);
    addEventListener("pointercancel", onUp);
  };

  useLayoutEffect(() => {
    const k = keepTop.current;
    if (k) {
      keepTop.current = null;
      const now = grid.current?.querySelector(`[data-card="${k.id}"]`)?.getBoundingClientRect().top;
      if (now !== undefined && now !== k.top) scrollBy(0, now - k.top);
    }
    const f = focusAfter.current;
    if (f) { focusAfter.current = null; grid.current?.querySelector<HTMLElement>(`[data-card="${f.id}"] ${f.sel}`)?.focus(); }
  });

  const ids = shownIds();
  const hidden = entries.filter((e) => e.hidden && has.has(e.id));
  return (
    <>
      <div className="cards dash" ref={grid}>
        {ids.map((id) => {
          const spec = specs.find((x) => x.id === id)!, e = entries.find((x) => x.id === id)!;
          const open = unlocked.has(id), wide = e.wide === null ? spec.defaultWide : e.wide;
          const btn = (cls: string, text: string, label: string, fn: () => void) =>
            <button type="button" className={`dl-btn ${cls}`} title={label} aria-label={`${label}: ${spec.title}`} onClick={fn}>{text}</button>;
          const startDrag = (ev: RPointerEvent) => drag(ev, id);
          const tools = (
            <>
              <button type="button" className="dl-btn dl-pin" aria-pressed={!open} aria-label={`${open ? "Pin" : "Unpin"} ${spec.title}`}
                title={open ? "Unlocked: drag to move. Click to pin it in place." : "Pinned. Click to unlock and move, resize or hide."}
                onClick={() => { const next = new Set(unlocked); if (open) next.delete(id); else next.add(id); setUnlocked(next); }}><PinIcon /></button>
              <div className="dl-bar" onPointerDown={startDrag}>
                <span className="dl-grip" aria-hidden="true">⠿ Drag to move</span>
                {btn("dl-up", "↑", "Move up", () => move(id, -1))}{btn("dl-down", "↓", "Move down", () => move(id, 1))}
                {btn("dl-width", wide ? "Half width" : "Full width", wide ? "Make it half width" : "Make it full width", () => {
                  focusAfter.current = { id, sel: ".dl-width" };
                  update(entries.map((x) => (x.id === id ? { ...x, wide: !wide } : x)));
                })}
                {btn("dl-hide", "Hide", "Hide", () => { const next = new Set(unlocked); next.delete(id); setUnlocked(next); update(entries.map((x) => (x.id === id ? { ...x, hidden: true } : x))); })}
              </div>
            </>
          );
          return (
            <DashCardContext.Provider key={id} value={{ id, tools, wide, headProps: { onPointerDown: startDrag },
              className: [open ? "dl-open" : "", dragging === id ? "dl-dragging" : ""].filter(Boolean).join(" ") }}>
              {spec.card}
            </DashCardContext.Provider>
          );
        })}
      </div>
      <div className="dl-foot">
        <span>Layout: click a widget's pin to move, resize or hide it.</span>
        {hidden.length ? <span className="dl-hidden">Hidden: {hidden.map((e) => (
          <button key={e.id} type="button" className="dl-btn dl-show" onClick={() => update(entries.map((x) => (x.id === e.id ? { ...x, hidden: false } : x)))}>{`Show ${title(e.id)}`}</button>
        ))}</span> : null}
        {layout ? <button type="button" className="dl-btn dl-reset" onClick={async () => {
          if (!confirm("Put the dashboard back to its default order, widths and widgets?")) return;
          try {
            await saving.current;
            await send("DELETE", "/api/dashboard/layout");
            setLayout(null); onSaved(null); setEntries(dlArrange(null, defaults)); setUnlocked(new Set());
          } catch (err) { showMessage(msg.current, (err as Error).message, false); }
        }}>Reset to default layout</button> : null}
        <span className="form-msg" role="status" aria-live="polite" ref={msg} />
      </div>
    </>
  );
}
