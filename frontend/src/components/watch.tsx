// Watchlists on the company page: the "Add to watchlist" button with its
// picker, and the line saying which lists it's on (watchButton(),
// watchPicker() and watchNote() in web/app.js).
import { Fragment, useEffect, useRef, useState, type FormEvent } from "react";
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
