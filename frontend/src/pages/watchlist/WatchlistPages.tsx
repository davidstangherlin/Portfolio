// Watchlists: named lists of companies, ETFs and LICs to follow, with notes
// and triggers. #/watchlists (or ?new=1) and #/watchlist/{id}.
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { Badge, ClickableRow, ErrorLine, Loading, PageHead } from "../../components/bits";
import { Card } from "../../components/Card";
import { ValuationPill, valuationStatus } from "../../components/common";
import { HelpTh } from "../../components/FieldHelp";
import { FilterableTable } from "../../components/FilterableTable";
import { Field, FormMessage, RowButton } from "../../components/forms";
import { MiniWheel } from "../../components/MiniWheel";
import { watchlistHref } from "../../components/watch";
import { getJSON, send } from "../../lib/api";
import { showMessage } from "../../lib/forms";
import { money, pct, plural, signClass, signedPct, sum } from "../../lib/format";
import { host } from "../../lib/host";
import type { Field as FilterField, Fields } from "../../lib/tableFilter";
import { FUNDS, fundHref, premText, PremCell, RetCell, RowTo, type Kind } from "../funds/common";
import { codeField, numField, SectionHead } from "../portfolio/holdings";

interface Trigger { label: string; met: boolean }
interface Entry {
  asx_code: string; company_name: string | null; security_type: string; held: boolean; note: string | null; triggers: Trigger[] | null; triggered: boolean;
  mos_above: number | null; yield_above: number | null; nta_discount_above: number | null; price_below: number | null; short_above: number | null;
  scores?: number[] | null; price: number | null; margin_of_safety_percent?: number | null; action?: string | null;
  day_change_percent?: number | null; premium_now?: number | null; return_1y?: number | null; distribution_yield_12m?: number | null;
  [key: string]: unknown;
}
interface Watchlist { watchlist_id: string; name: string; items: Entry[]; etfs: Entry[]; lics?: Entry[]; axes: string[]; checks_per_axis: number }
interface ListSummary { watchlist_id: string; name: string; companies: number; etfs: number; lics: number; triggered: number }
const afterChange = () => host().afterChange();

/* Each trigger with a tick when met now, or a dash when not. */
function TriggerList({ triggers }: { triggers: Trigger[] | null }) {
  if (!triggers || !triggers.length) return <span className="hint">none</span>;
  return <span className="trigs">{triggers.map((t) => <span key={t.label} className={`trig ${t.met ? "met" : ""}`} aria-label={`${t.label}: ${t.met ? "met" : "not met"}`}>
    <span className="mark" aria-hidden="true">{t.met ? "✓" : "–"}</span>{t.label}</span>)}</span>;
}

export function WatchlistsPage({ query }: { query?: string }) {
  const [d, setD] = useState<{ watchlists: ListSummary[] } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [name, setName] = useState("");
  const msg = useRef<HTMLParagraphElement>(null), create = useRef<HTMLDivElement>(null), nameIn = useRef<HTMLInputElement>(null);
  const wantNew = new URLSearchParams(query || "").get("new") === "1";
  useEffect(() => {
    let live = true;
    getJSON<{ watchlists: ListSummary[] }>("/api/watchlists").then((x) => {
      if (!live) return;
      setD(x);
      if (wantNew) setTimeout(() => { create.current?.firstElementChild?.scrollIntoView({ block: "center" }); nameIn.current?.focus(); }, 0); else window.scrollTo(0, 0);
    }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, [wantNew]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { const w = await send<{ watchlist_id: string }>("POST", "/api/watchlists", { name }); afterChange(); location.hash = watchlistHref(w); }
    catch (err) { showMessage(msg.current, (err as Error).message, false); }
  };
  if (error) return <ErrorLine error={error} />;
  if (!d) return <Loading text="Loading watchlists..." />;
  return (
    <>
      <PageHead title="Watchlists" sub={d.watchlists.length ? plural(d.watchlists.length, "watchlist") : null} />
      {d.watchlists.length ? (
        <div className="cards">{d.watchlists.map((w) => (
          <a key={w.watchlist_id} className="card pf-card" href={watchlistHref(w)}>
            <div className="pf-head"><h2>{w.name}</h2></div>
            <p className="hint">{w.companies || w.etfs || w.lics ? [w.companies ? plural(w.companies, "company", "companies") : null, w.etfs ? plural(w.etfs, "ETF") : null,
              w.lics ? plural(w.lics, "LIC") : null].filter(Boolean).join(", ") : "Nothing on it yet"}</p>
            {w.triggered ? <span className="tag">{`${plural(w.triggered, "trigger")} met`}</span> : null}
          </a>
        ))}</div>
      ) : <p className="empty">No watchlists yet. Create one below.</p>}
      <div className="cards" style={{ marginTop: 16 }} ref={create}>
        <Card title="New watchlist" hint="Companies, ETFs and LICs to follow without owning them. Add them here or with ☆ Add to watchlist on any company, ETF or LIC page.">
          <form className="form-grid" noValidate onSubmit={submit}>
            <Field label="Name"><input ref={nameIn} name="name" maxLength={60} placeholder="e.g. Dividend ideas" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <div className="form-actions"><button className="btn primary" type="submit">Create watchlist</button></div>
            <FormMessage ref={msg} />
          </form>
        </Card>
      </div>
    </>
  );
}

/* Watchlist tables as filter fields. */
const triggersField: FilterField<Entry> = { label: "Triggers", type: "text",
  get: (r) => (r.triggers && r.triggers.length ? (r.triggers.some((t) => t.met) ? "Met" : "Not met") : null),
  text: (r) => (r.triggers || []).map((t) => `${t.label} ${t.met ? "met" : "not met"}`).join("; ") };
const noteField: FilterField<Entry> = { label: "Note", type: "text", get: (r) => r.note };
const SHARE_FIELDS: Fields<Entry> = {
  score: { label: "Score", type: "num", get: (r) => (r.scores ? sum(r.scores) : null) },
  asx_code: codeField("Company"),
  price: numField("Price", "price", (v) => money(v)),
  margin_of_safety_percent: numField("Margin of safety", "margin_of_safety_percent", (v) => pct(v, 0)),
  valuation: { label: "Valuation", type: "text", get: (r) => valuationStatus(r.margin_of_safety_percent).label },
  action: { label: "Action", type: "text", get: (r) => r.action },
  triggers: triggersField, note: noteField,
};
const fundFields = (kind: Kind): Fields<Entry> => ({
  asx_code: codeField(FUNDS[kind].noun),
  price: numField(FUNDS[kind].price, "price", (v) => money(v)),
  day_change_percent: numField("Day move", "day_change_percent", (v) => signedPct(v)),
  [kind === "LIC" ? "premium_now" : "return_1y"]: kind === "LIC" ? numField("Premium/discount to NTA", "premium_now", premText) : numField("1-year return", "return_1y", (v) => signedPct(v)),
  distribution_yield_12m: numField("Yield (12 months)", "distribution_yield_12m", (v) => pct(v, 1)),
  triggers: triggersField, note: noteField,
});
const helpOr = (x: string, cls: string | undefined) => (host().fieldHelp(x) ? <HelpTh key={x || "act"} label={x} className={cls} tab /> : <th key={x || "act"} className={cls}>{x}</th>);

function ShareTable({ d, items, tp, edit, remove }: { d: Watchlist; items: Entry[]; tp: object; edit: (e: Entry) => void; remove: (e: Entry) => void }) {
  const heads = ["Score", "Company", "Price", "Margin of safety", "Valuation", "Action", "Triggers", "Note", ""];
  return (
    <div className="table-wrap"><table className="grid" {...tp}>
      <thead><tr>{heads.map((x, i) => helpOr(x, [i === 2 || i === 3 ? "num" : "", i === 0 ? "opt3" : "", i === 4 ? "opt4" : "", i === 2 || i === 7 ? "opt" : ""].join(" ").trim() || undefined))}</tr></thead>
      <tbody>{items.map((e) => (
        <ClickableRow key={e.asx_code} code={e.asx_code}>
          <td className="opt3">{e.scores ? <><MiniWheel scores={e.scores} axes={d.axes} max={d.checks_per_axis} /><span className="score-total">{sum(e.scores)}</span></> : null}</td>
          <td><span className="code">{e.asx_code}</span>{e.held ? <span className="held-tag">HELD</span> : null}<div className="name">{e.company_name || ""}</div></td>
          <td className="num opt">{money(e.price)}</td>
          <td className={`num ${signClass(e.margin_of_safety_percent) || ""}`.trim()}>{pct(e.margin_of_safety_percent, 0)}</td>
          <td className="opt4"><ValuationPill mos={e.margin_of_safety_percent} /></td>
          <td>{e.action ? <Badge action={e.action} /> : <span className="hint">not valued</span>}</td>
          <td><TriggerList triggers={e.triggers} /></td>
          <td className="opt"><div className="name note-cell" title={e.note || ""}>{e.note || ""}</div></td>
          <td className="act"><RowButton label="Edit" onClick={() => edit(e)} />{" "}<RowButton label="Remove" cls="danger" onClick={() => remove(e)} /></td>
        </ClickableRow>
      ))}</tbody>
    </table></div>
  );
}

function FundTable({ kind, items, tp, edit, remove }: { kind: Kind; items: Entry[]; tp: object; edit: (e: Entry) => void; remove: (e: Entry) => void }) {
  const F = FUNDS[kind];
  const heads = [F.noun, F.price, "Day move", kind === "LIC" ? "Premium/discount to NTA" : "1-year return", "Yield (12 months)", "Triggers", "Note", ""];
  return (
    <div className="table-wrap"><table className="grid" {...tp}>
      <thead><tr>{heads.map((x, i) => helpOr(x, [i >= 1 && i <= 4 ? "num" : "", i === 2 || i === 6 ? "opt4" : ""].join(" ").trim() || undefined))}</tr></thead>
      <tbody>{items.map((e) => (
        <RowTo key={e.asx_code} href={fundHref(kind, e.asx_code)}>
          <td><span className="code">{e.asx_code}</span>{e.held ? <span className="held-tag">HELD</span> : null}<div className="name">{e.company_name || ""}</div></td>
          <td className="num">{money(e.price)}</td>
          <RetCell v={e.day_change_percent} cls="opt4" />
          {kind === "LIC" ? <PremCell v={e.premium_now} /> : <RetCell v={e.return_1y} />}
          <td className="num">{pct(e.distribution_yield_12m, 1)}</td>
          <td><TriggerList triggers={e.triggers} /></td>
          <td className="opt4"><div className="name note-cell" title={e.note || ""}>{e.note || ""}</div></td>
          <td className="act"><RowButton label="Edit" onClick={() => edit(e)} />{" "}<RowButton label="Remove" cls="danger" onClick={() => remove(e)} /></td>
        </RowTo>
      ))}</tbody>
    </table></div>
  );
}

const BLANK = { asx_code: "", note: "", mos_above: "", yield_above: "", nta_discount_above: "", price_below: "", short_above: "" };
const str = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));

/* Add or edit an entry: the same form, since saving a company already on the list updates it. */
function EntryForm({ d, editing, cancel, reload }: { d: Watchlist; editing: Entry | null; cancel: () => void; reload: (note: string | null) => Promise<void> }) {
  const [v, setV] = useState(editing ? { asx_code: editing.asx_code, note: editing.note || "", mos_above: str(editing.mos_above), yield_above: str(editing.yield_above),
    nta_discount_above: str(editing.nta_discount_above), price_below: str(editing.price_below), short_above: str(editing.short_above) } : BLANK);
  const msg = useRef<HTMLParagraphElement>(null), form = useRef<HTMLFormElement>(null), noteIn = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) { form.current?.closest("section")?.scrollIntoView({ block: "center" }); noteIn.current?.focus(); } }, [editing]);
  const t = editing ? editing.security_type : null;
  const hide = { mos: t !== null && t !== "SHARE", dy: t === "SHARE", disc: t !== null && t !== "LIC", short: t !== null && t !== "SHARE" };
  const set = (k: keyof typeof BLANK) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const c = v.asx_code.trim().toUpperCase();
    if (!c) { showMessage(msg.current, "Enter an ASX code, such as BHP.", false); return; }
    try {
      await send("PUT", `/api/watchlists/${d.watchlist_id}/items/${encodeURIComponent(c)}`, { note: v.note, mos_above: hide.mos ? "" : v.mos_above,
        yield_above: hide.dy ? "" : v.yield_above, nta_discount_above: hide.disc ? "" : v.nta_discount_above, price_below: v.price_below, short_above: hide.short ? "" : v.short_above });
      afterChange();
      await reload(editing ? `Saved ${c}.` : `Added ${c}.`);
    } catch (err) { showMessage(msg.current, (err as Error).message, false); }
  };
  const dec = (k: keyof typeof BLANK, placeholder: string) => <input name={k} inputMode="decimal" autoComplete="off" placeholder={placeholder} value={v[k]} onChange={set(k)} />;
  return (
      <Card title={editing ? `Edit ${editing.asx_code}` : "Add a company, ETF or LIC"} hint="Triggers are optional; leave them blank to just follow it.">
        <form className="form-grid" noValidate onSubmit={submit} ref={form}>
          <Field label="Company, ETF or LIC"><input name="asx_code" list="company-list" maxLength={6} autoComplete="off" placeholder="BHP or VAS" style={{ textTransform: "uppercase" }}
            value={v.asx_code} readOnly={!!editing} onChange={set("asx_code")} /></Field>
          <Field label="Note"><input ref={noteIn} name="note" maxLength={500} autoComplete="off" placeholder="Why you're watching it" value={v.note} onChange={set("note")} /></Field>
          <Field label="Trigger: margin of safety above (%)" hint="Shares only. Met while the share is at least this far below estimated value." hidden={hide.mos}>{dec("mos_above", "e.g. 25")}</Field>
          <Field label="Trigger: yield above (%)" hint="ETFs and LICs. Met while the 12-month yield is above this." hidden={hide.dy}>{dec("yield_above", "e.g. 5")}</Field>
          <Field label="Trigger: discount to NTA of at least (%)" hint="LICs only. Met while the price is at least this far below the last NTA." hidden={hide.disc}>{dec("nta_discount_above", "e.g. 10")}</Field>
          <Field label="Trigger: price at or below ($)" hint="Met while the latest close is at or under this price.">{dec("price_below", "e.g. 38.50")}</Field>
          <Field label="Trigger: short interest above (%)" hint="Shares only. Met while more than this % of the company's shares are reported sold short (ASIC, a few days behind)." hidden={hide.short}>{dec("short_above", "e.g. 5")}</Field>
          <div className="form-actions"><button className="btn primary" type="submit">{editing ? "Save changes" : "Add to watchlist"}</button>
            <button className="btn" type="button" hidden={!editing || undefined} onClick={cancel}>Cancel</button></div>
          <FormMessage ref={msg} />
        </form>
      </Card>
  );
}

function SettingsForm({ d, reload }: { d: Watchlist; reload: (note: string | null) => Promise<void> }) {
  const [name, setName] = useState(d.name);
  const msg = useRef<HTMLParagraphElement>(null);
  return (
    <Card title="Settings">
      <form className="form-grid" noValidate onSubmit={async (ev) => {
        ev.preventDefault();
        try { await send("PATCH", `/api/watchlists/${d.watchlist_id}`, { name }); afterChange(); await reload("Renamed."); }
        catch (err) { showMessage(msg.current, (err as Error).message, false); }
      }}>
        <Field label="Name"><input name="name" value={name} maxLength={60} autoComplete="off" onChange={(e) => setName(e.target.value)} /></Field>
        <div className="form-actions"><button className="btn" type="submit">Rename</button>
          <button className="btn danger" type="button" onClick={async () => {
            if (!confirm(`Delete ${d.name}${d.items.length ? ` and its ${plural(d.items.length, "company", "companies")}, notes and triggers` : ""}? This can't be undone.`)) return;
            try { await send("DELETE", `/api/watchlists/${d.watchlist_id}`); afterChange(); location.hash = "#/watchlists"; }
            catch (err) { showMessage(msg.current, (err as Error).message, false); }
          }}>Delete watchlist</button></div>
        <FormMessage ref={msg} />
      </form>
    </Card>
  );
}

export function WatchlistPage({ id }: { id: string }) {
  const [d, setD] = useState<Watchlist | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [editing, setEditing] = useState<Entry | null>(null);
  const [version, setVersion] = useState(0);
  const [note, setNote] = useState<{ text: string; ok: boolean; n: number } | null>(null);
  const notice = useRef<HTMLParagraphElement>(null);
  const load = () => getJSON<Watchlist>(`/api/watchlists/${encodeURIComponent(id)}`);
  useEffect(() => {
    let live = true;
    load().then((x) => { if (live) { setD(x); window.scrollTo(0, 0); } }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, [id]);  // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    if (!notice.current) return;
    if (!note) { notice.current.textContent = ""; return; }
    showMessage(notice.current, note.text, note.ok);
    if (note.ok) notice.current.scrollIntoView({ block: "nearest" });
  }, [note]);
  const reload = async (text: string | null) => {
    const x = await load();
    setD(x); setEditing(null); setVersion((v) => v + 1);
    setNote(text ? { text, ok: true, n: Date.now() } : null);
  };
  if (error) return <ErrorLine error={error} />;
  if (!d) return <Loading text="Loading watchlist..." />;
  const remove = async (e: Entry) => {
    try { await send("DELETE", `/api/watchlists/${d.watchlist_id}/items/${e.asx_code}`); afterChange(); await reload(`Removed ${e.asx_code}.`); }
    catch (err) { setNote({ text: (err as Error).message, ok: false, n: Date.now() }); }
  };
  const lics = d.lics || [];
  const met = [...d.items, ...d.etfs, ...lics].filter((e) => e.triggered).length;
  const counts = [d.items.length ? plural(d.items.length, "company", "companies") : null, d.etfs.length ? plural(d.etfs.length, "ETF") : null,
    lics.length ? plural(lics.length, "LIC") : null].filter(Boolean);
  const both = d.etfs.length || lics.length;
  const fundBlock = (kind: Kind, items: Entry[]) => {
    const fields = fundFields(kind);
    return <><SectionHead title={FUNDS[kind].nouns} />
      <FilterableTable filterKey={`watch:${d.watchlist_id}:${kind}`} fields={fields} columns={[...Object.keys(fields), null]} rows={items}
        render={(shown, tp) => <FundTable kind={kind} items={shown} tp={tp} edit={setEditing} remove={remove} />} /></>;
  };
  return (
    <>
      <a className="back" href="#/watchlists">← Watchlists</a>
      <PageHead title={d.name} sub={counts.length ? `${counts.join(", ")}${met ? `, ${plural(met, "trigger")} met` : ""}` : null} />
      <FormMessage ref={notice} />
      {d.items.length ? <>{both ? <SectionHead title="Shares" /> : null}
        <FilterableTable filterKey={`watch:${d.watchlist_id}:SHARE`} fields={SHARE_FIELDS} columns={["score", "asx_code", "price", "margin_of_safety_percent", "valuation", "action", "triggers", "note", null]}
          rows={d.items} render={(shown, tp) => <ShareTable d={d} items={shown} tp={tp} edit={setEditing} remove={remove} />} /></> : null}
      {d.etfs.length ? fundBlock("ETF", d.etfs) : null}
      {lics.length ? fundBlock("LIC", lics) : null}
      {!d.items.length && !d.etfs.length && !lics.length ? <p className="empty">Nothing on this list yet. Add a company, ETF or LIC below, or use ☆ Add to watchlist on its page.</p> : null}
      <div className="cards dash" style={{ marginTop: 16 }}>
        <EntryForm key={`${version}:${editing ? editing.asx_code : ""}`} d={d} editing={editing} cancel={() => reload(null)} reload={reload} />
        <SettingsForm key={`s${version}`} d={d} reload={reload} />
      </div>
    </>
  );
}
