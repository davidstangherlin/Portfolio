// One portfolio: #/portfolio/{id}. Holdings, a buy or sell form, settings,
// open parcels, sales and capital gains by financial year.
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { ErrorLine, Loading } from "../../components/bits";
import { Card } from "../../components/Card";
import { Field, FormMessage, RowButton, todayIso } from "../../components/forms";
import { getJSON, send } from "../../lib/api";
import { showMessage } from "../../lib/forms";
import { fmt, longDate, money, plural, signClass, signed } from "../../lib/format";
import { host } from "../../lib/host";
import { KindTag } from "../funds/common";
import { discountText, type TaxType } from "./common";
import { HoldingsSections, PortfolioStrip, type HoldingLine, type Sections, type Totals } from "./holdings";
import { TaxSelect, TaxTag } from "./PortfoliosPage";

interface Parcel { holding_id: string; short_id: string; asx_code: string; method: string; buy_date: string; units: number; buy_price: number; cost_base: number; gain: number | null; discount_from: string | null }
interface Sale { holding_id: string; asx_code: string; sell_date: string; units: number; proceeds: number; cost_base: number; gain: number; discount_eligible: boolean; financial_year: string }
interface CgtYear { financial_year: string; sales: number; discountable_gains: number; non_discountable_gains: number; capital_losses: number; net_capital_gain: number; unused_losses: number }
interface PortfolioData {
  portfolio: { portfolio_id: string; name: string; archived: boolean; tax_type: string; tax_type_label: string; discount_rate: number };
  positions: (HoldingLine & { units: number })[]; sections: Sections; totals: Omit<Totals, "holdings">;
  parcels: Parcel[]; sales: Sale[]; cgt: CgtYear[]; tax_types: TaxType[]; etf_codes?: string[]; lic_codes?: string[];
}
type Reload = (note: string | null) => Promise<void>;
const money0 = (v: number) => money(v, 0);
const afterChange = () => host().afterChange();
const err = (e: unknown) => (e as Error).message;

const METHODS: [string, string][] = [["PURCHASE", "Purchase"], ["DRP", "Dividend reinvestment (DRP)"], ["BONUS", "Bonus issue"], ["TRANSFER", "Transfer in"], ["OTHER", "Other"]];
const num = (name: string, placeholder = "") => <input name={name} inputMode="decimal" autoComplete="off" placeholder={placeholder} />;
const dateIn = () => <input type="date" name="date" defaultValue={todayIso()} max={todayIso()} required />;

/* Buy or sell form. Sell offers only what the portfolio holds, and which parcels go first. */
function TradeCard({ d, reload }: { d: PortfolioData; reload: Reload }) {
  const pf = d.portfolio;
  const [mode, setMode] = useState<"BUY" | "SELL">("BUY");
  const [sellCode, setSellCode] = useState(d.positions.length ? d.positions[0].asx_code : "");
  const [busy, setBusy] = useState(false);
  const msg = useRef<HTMLParagraphElement>(null);
  if (pf.archived) return <Card title="Record a trade"><p className="empty">This portfolio is archived. Unarchive it in Settings to record trades.</p></Card>;
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data: Record<string, string> = Object.fromEntries([...new FormData(e.currentTarget).entries()].map(([k, v]) => [k, String(v)]));
    if (data.order && data.order.startsWith("parcel:")) { data.parcel_id = data.order.slice(7); data.order = "fifo"; }
    setBusy(true);
    try {
      if (mode === "BUY") {
        const r = await send<{ units: number; asx_code: string; cost_base: number; discount_from: string }>("POST", `/api/portfolios/${pf.portfolio_id}/buys`, data);
        afterChange();
        await reload(`Recorded: ${fmt(r.units, 0)} ${r.asx_code}, cost base ${money(r.cost_base)}.${pf.discount_rate > 0 ? ` CGT discount applies to sales from ${longDate(r.discount_from)}.` : ""}`);
      } else {
        const r = await send<{ units: number; parcels: number; proceeds: number; gain: number; discounted_units: number }>("POST", `/api/portfolios/${pf.portfolio_id}/sales`, data);
        afterChange();
        await reload(`Recorded: sold ${fmt(r.units, 0)} units from ${plural(r.parcels, "parcel")}, proceeds ${money(r.proceeds)}, ` +
          `${r.gain >= 0 ? "capital gain" : "capital loss"} ${money(Math.abs(r.gain))}` +
          `${pf.discount_rate > 0 ? ` (${fmt(r.discounted_units, 0)} units eligible for the discount)` : ""}.`);
      }
    } catch (e2) { showMessage(msg.current, err(e2), false); setBusy(false); }
  };
  const parcels = d.parcels.filter((p) => p.asx_code === sellCode);
  return (
    <Card title="Record a trade">
      <div className="segmented" role="group" aria-label="Trade type">
        {([["BUY", "Buy"], ["SELL", "Sell"]] as const).map(([m, label]) => (
          <button key={m} type="button" data-mode={m} aria-pressed={m === mode} disabled={m === "SELL" && !d.positions.length}
            onClick={() => { setMode(m); if (msg.current) msg.current.textContent = ""; }}>{label}</button>
        ))}
      </div>
      <form className="form-grid" noValidate onSubmit={submit} key={mode}>
        {mode === "BUY" ? (
          <>
            <Field label="Company or ETF"><input name="asx_code" list="company-list" maxLength={6} autoComplete="off" placeholder="e.g. BHP or VAS" style={{ textTransform: "uppercase" }} /></Field>
            <Field label="Units">{num("units")}</Field>
            <Field label="Price per share or unit">{num("price", "$")}</Field>
            <Field label="Trade date">{dateIn()}</Field>
            <Field label="Brokerage" hint="Adds to the cost base.">{num("brokerage", "$0.00")}</Field>
            <Field label="How acquired"><select name="method">{METHODS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></Field>
            <Field label="Broker or account"><input name="broker" maxLength={50} autoComplete="off" /></Field>
            <Field label="Notes"><input name="notes" maxLength={500} autoComplete="off" /></Field>
          </>
        ) : (
          <>
            <Field label="Company or ETF">
              <select name="asx_code" value={sellCode} onChange={(e) => setSellCode(e.target.value)}>
                {d.positions.map((p) => <option key={p.asx_code} value={p.asx_code}>{`${p.asx_code} (${fmt(p.units, 0)} units)`}</option>)}
              </select>
            </Field>
            <Field label="Units">{num("units")}</Field>
            <Field label="Price per share or unit">{num("price", "$")}</Field>
            <Field label="Trade date">{dateIn()}</Field>
            <Field label="Brokerage" hint="Reduces the capital proceeds.">{num("brokerage", "$0.00")}</Field>
            <Field label="Which parcels" hint="Smallest taxable gain counts this portfolio's CGT discount.">
              <select name="order" key={sellCode}>
                <option value="fifo">Oldest parcels first</option>
                <option value="min-tax">Smallest taxable gain first</option>
                {parcels.length > 1 ? parcels.map((p) => <option key={p.holding_id} value={`parcel:${p.holding_id}`}>{`Only parcel ${p.short_id}: ${fmt(p.units, 0)} units bought ${longDate(p.buy_date)}`}</option>) : null}
              </select>
            </Field>
          </>
        )}
        <div className="form-actions"><button className="btn primary" type="submit" disabled={busy}>{mode === "BUY" ? "Record buy" : "Record sale"}</button></div>
        <FormMessage ref={msg} />
      </form>
    </Card>
  );
}

function SettingsCard({ d, reload }: { d: PortfolioData; reload: Reload }) {
  const pf = d.portfolio;
  const [name, setName] = useState(pf.name), [tax, setTax] = useState(pf.tax_type);
  const msg = useRef<HTMLParagraphElement>(null);
  const patch = async (body: object, note: string) => {
    try { await send("PATCH", `/api/portfolios/${pf.portfolio_id}`, body); afterChange(); await reload(note); }
    catch (e) { showMessage(msg.current, err(e), false); }
  };
  const open = d.parcels.length, sales = d.sales.length;
  return (
    <Card title="Settings">
      <form className="form-grid" noValidate onSubmit={(e) => { e.preventDefault(); patch({ name, tax_type: tax }, "Saved."); }}>
        <Field label="Name"><input name="name" value={name} maxLength={60} autoComplete="off" onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Owner's tax type" hint={d.sales.length ? "Changing it changes the CGT discount on the sales already recorded here." : null}><TaxSelect types={d.tax_types} value={tax} onChange={setTax} /></Field>
        <div className="form-actions"><button className="btn" type="submit">Save</button></div>
      </form>
      <div className="danger-zone">
        <div>
          {pf.archived
            ? <button className="btn" type="button" onClick={() => patch({ archived: false }, "Unarchived.")}>Unarchive</button>
            : <button className="btn" type="button" disabled={open > 0} onClick={() => {
                if (confirm(`Archive ${pf.name}? It moves out of the menu and dashboard; its sales stay in the CGT report.`)) patch({ archived: true }, "Archived.");
              }}>Archive</button>}
          <span className="field-hint">{open ? "Archive once every parcel is sold." : "Keeps the sale records for tax, out of the way."}</span>
        </div>
        <div>
          <button className="btn danger" type="button" disabled={sales > 0} onClick={async () => {
            if (!confirm(`Delete ${pf.name}${open ? ` and its ${plural(open, "open parcel")}` : ""}? This can't be undone.`)) return;
            try { await send("DELETE", `/api/portfolios/${pf.portfolio_id}`); afterChange(); location.hash = "#/portfolios"; }
            catch (e) { showMessage(msg.current, err(e), false); }
          }}>Delete portfolio</button>
          <span className="field-hint">{sales ? "Has sales, which are tax records: archive it instead." : "Removes it and any open parcels."}</span>
        </div>
      </div>
      <FormMessage ref={msg} />
    </Card>
  );
}

const fundTag = (d: PortfolioData, code: string) => ((d.etf_codes || []).includes(code) ? <KindTag kind="ETF" /> : (d.lic_codes || []).includes(code) ? <KindTag kind="LIC" /> : null);

function ParcelsCard({ d, reload, fail }: { d: PortfolioData; reload: Reload; fail: (text: string) => void }) {
  const gets = d.portfolio.discount_rate > 0;
  const remove = async (p: Parcel) => {
    if (!confirm(`Delete parcel ${p.short_id}: ${fmt(p.units, 0)} ${p.asx_code} bought ${longDate(p.buy_date)}?\n\nOnly for a parcel entered by mistake. This can't be undone.`)) return;
    try { await send("DELETE", `/api/parcels/${p.holding_id}`); afterChange(); await reload(`Deleted parcel ${p.short_id}.`); }
    catch (e) { fail(err(e)); }
  };
  const heads = ["Company", "Parcel", "Bought", "Units", "Buy price", "Cost base", "Gain", gets ? "CGT discount from" : "CGT discount", ""];
  return (
    <Card title="Open parcels" wide hint="Each buy is its own parcel for tax. Delete is for a parcel entered by mistake.">
      {d.parcels.length ? (
        <div className="table-wrap"><table className="grid compact">
          <thead><tr>{heads.map((x, i) => <th key={i} className={[i >= 3 && i <= 6 ? "num" : "", [1, 4, 7].includes(i) ? "opt" : ""].join(" ").trim() || undefined}>{x}</th>)}</tr></thead>
          <tbody>{d.parcels.map((p) => (
            <tr key={p.holding_id} className="static">
              <td><span className="code">{p.asx_code}</span>{fundTag(d, p.asx_code)}{p.method !== "PURCHASE" ? <span className="tag muted sm">{p.method}</span> : null}</td>
              <td className="opt mono">{p.short_id}</td>
              <td>{longDate(p.buy_date)}</td>
              <td className="num">{fmt(p.units, 0)}</td>
              <td className="num opt">{money(p.buy_price, 3)}</td>
              <td className="num">{money(p.cost_base)}</td>
              <td className={`num ${signClass(p.gain) || ""}`.trim()}>{signed(p.gain, money0)}</td>
              <td className="opt">{p.discount_from ? (p.discount_from <= todayIso() ? "eligible now" : longDate(p.discount_from)) : "n/a"}</td>
              <td className="act"><RowButton label="Delete" cls="danger" onClick={() => remove(p)} /></td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="empty">No open parcels.</p>}
    </Card>
  );
}

function SalesCard({ d, reload, fail }: { d: PortfolioData; reload: Reload; fail: (text: string) => void }) {
  const gets = d.portfolio.discount_rate > 0;
  const undo = async (s: Sale) => {
    if (!confirm(`Undo the sale of ${fmt(s.units, 0)} ${s.asx_code} on ${longDate(s.sell_date)}?\n\nThe units go back into the open parcel they came from.`)) return;
    try { await send("POST", `/api/parcels/${s.holding_id}/undo-sale`); afterChange(); await reload(`Sale undone: ${fmt(s.units, 0)} ${s.asx_code} are open again.`); }
    catch (e) { fail(err(e)); }
  };
  const heads = ["Company", "Sold", "Units", "Proceeds", "Cost base", "Gain", "CGT discount", "Financial year", ""];
  return (
    <Card title="Sales" wide hint="Every sale recorded, newest first. Undo is for a sale entered by mistake.">
      {d.sales.length ? (
        <div className="table-wrap"><table className="grid compact">
          <thead><tr>{heads.map((x, i) => <th key={i} className={[i >= 2 && i <= 5 ? "num" : "", [3, 4, 7].includes(i) ? "opt" : "", i === 6 ? "opt2" : ""].join(" ").trim() || undefined}>{x}</th>)}</tr></thead>
          <tbody>{d.sales.map((s) => (
            <tr key={s.holding_id} className="static">
              <td><span className="code">{s.asx_code}</span>{fundTag(d, s.asx_code)}</td>
              <td>{longDate(s.sell_date)}</td>
              <td className="num">{fmt(s.units, 0)}</td>
              <td className="num opt">{money(s.proceeds)}</td>
              <td className="num opt">{money(s.cost_base)}</td>
              <td className={`num ${signClass(s.gain) || ""}`.trim()}>{signed(s.gain, (v) => money(v))}</td>
              <td className="opt2">{gets ? (s.discount_eligible ? "Yes" : "No") : "n/a"}</td>
              <td className="opt">{s.financial_year}</td>
              <td className="act"><RowButton label="Undo" onClick={() => undo(s)} /></td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="empty">No sales recorded.</p>}
    </Card>
  );
}

function CgtCard({ d }: { d: PortfolioData }) {
  const pf = d.portfolio;
  const heads = ["Financial year", "Sales", "Gains with discount", "Other gains", "Losses", "Net capital gain", "Losses carried forward"];
  return (
    <Card title="Capital gains by financial year" wide hint={`${pf.tax_type_label}: ${discountText(pf.discount_rate)}. Losses are set against gains that don't get the discount first.`}>
      {d.cgt.length ? (
        <div className="table-wrap"><table className="grid compact">
          <thead><tr>{heads.map((x, i) => <th key={i} className={[i ? "num" : "", i === 1 || i === 6 ? "opt2" : ""].join(" ").trim() || undefined}>{x}</th>)}</tr></thead>
          <tbody>{d.cgt.map((y) => (
            <tr key={y.financial_year} className="static">
              <td>{y.financial_year}</td><td className="num opt2">{fmt(y.sales, 0)}</td>
              <td className="num">{money(y.discountable_gains)}</td><td className="num">{money(y.non_discountable_gains)}</td>
              <td className="num">{money(y.capital_losses)}</td><td className="num strong">{money(y.net_capital_gain)}</td>
              <td className="num opt2">{money(y.unused_losses)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="empty">Appears once a sale is recorded.</p>}
      <p className="hint" style={{ marginTop: 8 }}>A record-keeping aid, not tax advice. Losses carried forward from earlier years aren't included; confirm anything you lodge with the ATO or your accountant.</p>
    </Card>
  );
}

export function PortfolioPage({ id }: { id: string }) {
  const [d, setD] = useState<PortfolioData | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [note, setNote] = useState<{ text: string; ok: boolean; n: number } | null>(null);
  const [version, setVersion] = useState(0);
  const notice = useRef<HTMLParagraphElement>(null);
  const load = async () => getJSON<PortfolioData>(`/api/portfolios/${encodeURIComponent(id)}`);
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
  const reload: Reload = async (text) => {
    const x = await load();
    setD(x); setVersion((v) => v + 1);
    if (text) setNote({ text, ok: true, n: Date.now() }); else setNote(null);
  };
  const fail = (text: string) => setNote({ text, ok: false, n: Date.now() });
  if (error) return <ErrorLine error={error} />;
  if (!d) return <Loading text="Loading portfolio..." />;
  const pf = d.portfolio;
  return (
    <>
      <a className="back" href="#/portfolios">← Portfolios</a>
      <div className="page-head"><h1>{pf.name}</h1><TaxTag p={pf} />{pf.archived ? <span className="tag muted">Archived</span> : null}</div>
      <FormMessage ref={notice} />
      {d.positions.length ? <PortfolioStrip pf={{ ...d.totals, holdings: d.positions }} /> : null}
      {d.positions.length ? <div style={{ marginTop: 16 }}><HoldingsSections lines={d.positions} sections={d.sections} filterKey={`portfolio:${pf.portfolio_id}`} /></div> : null}
      <div className="cards dash" style={{ marginTop: 16 }}>
        <TradeCard key={`t${version}`} d={d} reload={reload} />
        <SettingsCard key={`s${version}`} d={d} reload={reload} />
        <ParcelsCard d={d} reload={reload} fail={fail} />
        <SalesCard d={d} reload={reload} fail={fail} />
        <CgtCard d={d} />
      </div>
    </>
  );
}
