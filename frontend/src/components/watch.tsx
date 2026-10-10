// Watchlists on the company page: the "Add to watchlist" button with its
// picker, and the line saying which lists it's on (watchButton(),
// watchPicker() and watchNote() in web/app.js).
import { Fragment, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { send } from "../lib/api";
import { showMessage } from "../lib/forms";
import { host } from "../lib/host";

export interface WatchEntry {
  watchlist_id: string; name: string; member: boolean;
  triggers?: unknown[] | null; triggered?: boolean; note?: string | null;
}

export const watchlistHref = (w: { watchlist_id: string }) => `#/watchlist/${w.watchlist_id}`;

/* "On Core, Dividends (trigger met)." Hidden when on none. */
export function WatchNote({ lists }: { lists: WatchEntry[] }) {
  const on = lists.filter((l) => l.member);
  return (
    <p className="hint watch-note" id="watch-note" hidden={!on.length || undefined}>
      {on.length ? <>On {on.map((l, i) => (
        <Fragment key={l.watchlist_id}>{i ? ", " : ""}<a href={watchlistHref(l)}>{l.name}</a>
          {l.triggered ? " (trigger met)" : l.triggers && l.triggers.length ? " (triggers set)" : ""}</Fragment>
      ))}.</> : null}
    </p>
  );
}

/* The tick boxes and "new watchlist" form. `changed` runs after each change with the new lists. */
export function WatchPicker({ code, lists, changed }: { code: string; lists: WatchEntry[]; changed: (next: WatchEntry[]) => void }) {
  const msg = useRef<HTMLParagraphElement>(null);
  const [name, setName] = useState("");
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const w = await send<WatchEntry>("POST", "/api/watchlists", { name, asx_code: code });
      setName("");
      changed([...lists, { ...w, member: true }]);
    } catch (err) { showMessage(msg.current, (err as Error).message, false); }
  };
  const toggle = async (l: WatchEntry, checked: boolean) => {
    try {
      if (checked) await send("PUT", `/api/watchlists/${l.watchlist_id}/items/${code}`, {});
      else await send("DELETE", `/api/watchlists/${l.watchlist_id}/items/${code}`);
      changed(lists.map((x) => x.watchlist_id !== l.watchlist_id ? x
        : checked ? { ...x, member: true, triggers: [], triggered: false, note: null } : { ...x, member: false }));
    } catch (err) { showMessage(msg.current, (err as Error).message, false); }
  };
  return (
    <>
      <h3>Watchlists</h3>
      {lists.length ? (
        <div className="watch-options">{lists.map((l) => (
          <label key={l.watchlist_id}><input type="checkbox" checked={l.member} onChange={(e) => toggle(l, e.target.checked)} />{l.name}</label>
        ))}</div>
      ) : <p className="hint">No watchlists yet. Name one to start it with this company.</p>}
      <form className="watch-new" onSubmit={create}>
        <input maxLength={60} placeholder="New watchlist name" autoComplete="off" aria-label="New watchlist name" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="btn small">Add</button>
      </form>
      <p className="form-msg" role="status" aria-live="polite" ref={msg} />
      <p className="hint" style={{ margin: "8px 0 0" }}>Notes and triggers: open the list from <a href="#/watchlists">Watchlists</a>.</p>
    </>
  );
}

export function WatchButton({ code, lists, onChange }: { code: string; lists: WatchEntry[]; onChange: (next: WatchEntry[]) => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  const on = lists.filter((l) => l.member).length;
  return (
    <div className="watch-wrap">
      <button type="button" className={`btn small watch-btn${on ? " on" : ""}`} aria-haspopup="true" aria-expanded={open}
        onClick={(e) => { e.nativeEvent.stopPropagation(); setOpen(!open); }}>{on ? "★ On watchlist" : "☆ Add to watchlist"}</button>
      <div className="watch-panel" role="dialog" aria-label="Watchlists" hidden={!open || undefined} onClick={(e) => e.nativeEvent.stopPropagation()}>
        <WatchPicker code={code} lists={lists} changed={(next) => { host().afterChange(); onChange(next); }} />
      </div>
    </div>
  );
}

/* ---------- list pages (screener, ETFs, LICs): a star on the left of each row ----------
   ☆ adds it to a watchlist, ★ shows it's on one; either opens the same picker as
   the company page, floating under the star (watchCell() in web/app.js). */
export interface ListRow { asx_code: string; watchlists: string[] }
export interface PageList { watchlist_id: string; name: string }

let closeOpenPop: ((refocus?: boolean) => void) | null = null;
if (typeof document !== "undefined") {
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && closeOpenPop) closeOpenPop(true); });
  window.addEventListener("hashchange", () => closeOpenPop && closeOpenPop());
}

function WatchPop({ anchor, r, lists, onClose, onChanged }: { anchor: HTMLElement; r: ListRow; lists: PageList[]; onClose: (refocus?: boolean) => void; onChanged: (entries: WatchEntry[]) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [entries, setEntries] = useState<WatchEntry[]>(() => lists.map((w) => ({ ...w, member: r.watchlists.includes(w.name) })));
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!matchMedia("(max-width: 560px)").matches) {  // phones: a fixed panel near the top (style.css)
      const a = anchor.getBoundingClientRect(), box = el.getBoundingClientRect();
      const below = a.bottom + 6 + box.height <= innerHeight - 8;
      el.style.left = `${scrollX + Math.max(8, Math.min(a.left, innerWidth - box.width - 8))}px`;
      el.style.top = `${scrollY + (below ? a.bottom + 6 : Math.max(8, a.top - 6 - box.height))}px`;
    }
    ((el.querySelector("input") as HTMLElement | null) || el).focus();
    const outside = (e: MouseEvent) => { if (!el.contains(e.target as Node) && !anchor.contains(e.target as Node)) onClose(); };
    document.addEventListener("click", outside);
    return () => document.removeEventListener("click", outside);
  }, []);
  return createPortal(
    <div className="watch-panel watch-pop" role="dialog" aria-label={`Watchlists for ${r.asx_code}`} ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Escape") onClose(true); }}>
      <WatchPicker code={r.asx_code} lists={entries} changed={(next) => { setEntries(next); onChanged(next); }} />
    </div>, document.body);
}

export function WatchCell({ r, lists, onChange }: { r: ListRow; lists: PageList[]; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const on = r.watchlists;
  const close = (refocus = false) => { setOpen(false); closeOpenPop = null; if (refocus) btn.current?.focus(); };
  return (
    <td className="watch-cell">
      <button ref={btn} type="button" className={`watch-toggle${on.length ? " on" : ""}`} aria-haspopup="dialog" aria-expanded={open}
        title={on.length ? `On watchlist: ${on.join(", ")}. Click to change.` : "Add to a watchlist"}
        aria-label={on.length ? `${r.asx_code} is on watchlist ${on.join(", ")}: change` : `Add ${r.asx_code} to a watchlist`}
        onClick={(e) => {
          e.stopPropagation();
          if (open) { close(); return; }  // a second click on the same star closes it
          if (closeOpenPop) closeOpenPop();
          closeOpenPop = close; setOpen(true);
        }}
        onKeyDown={(e) => e.stopPropagation()}>{on.length ? "★" : "☆"}</button>
      {open && btn.current ? <WatchPop anchor={btn.current} r={r} lists={lists} onClose={(refocus) => close(refocus)} onChanged={(entries) => {
        for (const w of entries) if (!lists.some((l) => l.watchlist_id === w.watchlist_id)) lists.push({ watchlist_id: w.watchlist_id, name: w.name });
        r.watchlists = entries.filter((w) => w.member).map((w) => w.name);
        host().afterChange();
        onChange();
      }} /> : null}
    </td>
  );
}
export const WatchHead = () => <th className="watch-cell" scope="col" title="Watchlist"><span className="sr-only">Watchlist</span></th>;
