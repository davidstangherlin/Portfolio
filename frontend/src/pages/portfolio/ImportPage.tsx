// Import from a broker: #/portfolios/import (docs/kb/features/broker-import.md).
// Nothing is saved until Import is pressed.
import { useEffect, useRef, useState } from "react";
import { Loading, PageHead } from "../../components/bits";
import { Card } from "../../components/Card";
import { FormMessage, todayIso } from "../../components/forms";
import { HelpLink } from "../../components/HelpLink";
import { getJSON, send } from "../../lib/api";
import { showMessage } from "../../lib/forms";
import { fmt, longDate, money, plural } from "../../lib/format";
import { host } from "../../lib/host";
import type { PortfolioSummary, TaxType } from "./common";

const IMPORT_FIELDS: [string, string][] = [["code", "ASX code"], ["side", "Buy or sell"], ["units", "Units"], ["price", "Price"], ["avg_cost", "Average cost"],
  ["total_cost", "Total cost"], ["date", "Date"], ["brokerage", "Brokerage"], ["details", "Details (B 100 BHP @ 45.00)"],
  ["debit", "Debit"], ["credit", "Credit"], ["market", "Market"], ["currency", "Currency"]];
const IMPORT_STATUS: Record<string, [string, string]> = { new: ["Ready", "under"], duplicate: ["Already in Sift", "none"], check: ["Check the code", "fair"], skip: ["Skipped", "none"] };

interface Line { row: number; include: boolean; status: string; reason: string | null; date: string | null; code: string | null; side: string | null; units: number | null; price: number | null; brokerage: number | null }
interface Preview {
  filename: string; broker: string; kind: string; holdings_date: string; mapping: Record<string, number>; headings: string[]; missing: string[];
  brokers: { broker_id: string; name: string }[]; lines: Line[]; counts: { new: number; check: number; duplicate: number; skip: number };
}
interface Result { bought: number; sold: number; portfolio: string; portfolio_id: string; problems: { row: number; code: string; reason: string }[] }

export function ImportPage() {
  const [pf, setPf] = useState<{ portfolios: PortfolioSummary[]; tax_types: TaxType[] } | null>(null);
  const [st, setSt] = useState({ filename: "", content: "", broker: "", kind: "", mapping: {} as Record<string, number | "">, holdings_date: todayIso(), portfolio_id: "" });
  const [d, setD] = useState<Preview | null>(null);
  const [brokers, setBrokers] = useState<{ broker_id: string; name: string }[]>([]);
  const [ticks, setTicks] = useState<Map<number, boolean>>(new Map());
  const [newName, setNewName] = useState(""), [taxType, setTaxType] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const msg = useRef<HTMLParagraphElement>(null), msg2 = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    getJSON<{ portfolios: PortfolioSummary[]; tax_types: TaxType[] }>("/api/portfolios").then((x) => {
      setPf(x);
      const active = x.portfolios.filter((p) => !p.archived);
      setSt((s) => ({ ...s, portfolio_id: active.length ? active[0].portfolio_id : "" }));
      setTaxType(x.tax_types.length ? x.tax_types[0].tax_type : "");
      window.scrollTo(0, 0);
    });
  }, []);

  const load = async (next: typeof st) => {
    setSt(next);
    showMessage(msg.current, "Reading the file...", true);
    try {
      const x = await send<Preview>("POST", "/api/portfolios/import/preview", { filename: next.filename, content: next.content, broker: next.broker || null,
        kind: next.kind || null, mapping: next.mapping, holdings_date: next.holdings_date, portfolio_id: next.portfolio_id || null });
      if (msg.current) msg.current.textContent = "";
      if (!brokers.length) setBrokers(x.brokers);
      setD(x); setResult(null);
      setTicks(new Map(x.lines.map((l) => [l.row, l.include])));
    } catch (err) { showMessage(msg.current, (err as Error).message, false); setD(null); }
  };
  const pick = (f: File | undefined) => {
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => load({ ...st, filename: f.name, content: String(reader.result).split(",")[1] || "", mapping: {}, kind: "" });
    reader.readAsDataURL(f);
  };
  const go = async () => {
    if (!d) return;
    if (!st.portfolio_id && !newName.trim()) { showMessage(msg2.current, "Name the new portfolio first.", false); return; }
    try {
      const r = await send<Result>("POST", "/api/portfolios/import", { filename: st.filename, content: st.content, broker: st.broker || d.broker, kind: d.kind,
        mapping: d.mapping, holdings_date: d.holdings_date, portfolio_id: st.portfolio_id || null, new_portfolio: st.portfolio_id ? null : newName,
        tax_type: taxType, rows: [...ticks].filter(([, on]) => on).map(([row]) => row) });
      host().afterChange();
      setResult(r);
      window.scrollTo(0, 0);
    } catch (err) { showMessage(msg2.current, (err as Error).message, false); }
  };

  if (!pf) return <><PageHead title="Import from a broker" /><Loading text="Loading..." /></>;
  const portfolios = pf.portfolios.filter((p) => !p.archived);
  let out = null;
  if (result) {
    out = (
      <Card title="Imported">
        <p>{`${plural(result.bought, "buy", "buys")} and ${plural(result.sold, "sale")} added to ${result.portfolio}.`}</p>
        {result.problems.length ? <><p className="error">{`${plural(result.problems.length, "line")} couldn't be added:`}</p>
          <ul>{result.problems.map((p) => <li key={p.row}>{`Row ${p.row} (${p.code}): ${p.reason}`}</li>)}</ul></> : null}
        <p><a className="btn primary" href={`#/portfolio/${result.portfolio_id}`}>Open the portfolio</a></p>
      </Card>
    );
  } else if (d) {
    const c = d.counts;
    const cols = IMPORT_FIELDS.filter(([f]) => d.kind === "trades" ? !["avg_cost", "total_cost"].includes(f) : !["side", "date", "brokerage", "details", "debit", "credit"].includes(f));
    out = (
      <>
        <div className="cards">
          <Card title="2. Check what was found" hint={`${d.filename}: ${d.broker !== "other" ? `looks like ${d.brokers.find((b) => b.broker_id === d.broker)!.name}. ` : ""}${plural(c.new, "line")} ready${c.check ? `, ${c.check} to check` : ""}${c.duplicate ? `, ${c.duplicate} already in Sift` : ""}${c.skip ? `, ${c.skip} skipped` : ""}.`}>
            <div className="segmented" role="group" aria-label="What the file holds">
              {([["trades", "Trade history"], ["holdings", "Holdings now"]] as const).map(([k, t]) => <button key={k} type="button" aria-pressed={d.kind === k} onClick={() => load({ ...st, kind: k })}>{t}</button>)}
            </div>
            {d.kind === "holdings" ? (
              <label className="field"><span className="field-label">Bought on</span>
                <input type="date" value={d.holdings_date} max={todayIso()} onChange={(e) => load({ ...st, holdings_date: e.target.value })} />
                <span className="field-hint">A holdings file has no buy dates. Use your earliest buy date if you know it; you can edit each parcel later. It decides when the CGT discount applies.</span></label>
            ) : null}
            {d.missing.length ? <p className="error">{`Choose the ${d.missing.join(" and ")} column below.`}</p> : null}
            <details className="import-cols" open={d.missing.length > 0 || undefined}><summary>Columns</summary>
              <div className="import-map">{cols.map(([f, label]) => (
                <label key={f} className="field"><span className="field-label">{label}</span>
                  <select value={d.mapping[f] === undefined ? "" : String(d.mapping[f])} onChange={(e) => load({ ...st, mapping: { ...st.mapping, [f]: e.target.value === "" ? "" : Number(e.target.value) } })}>
                    <option value="">Not in this file</option>
                    {d.headings.map((hd, i) => <option key={i} value={i}>{hd}</option>)}
                  </select></label>
              ))}</div>
            </details>
          </Card>
          <Card title="3. Where to put them">
            <label className="field"><span className="field-label">Import into</span>
              <select aria-label="Import into" value={st.portfolio_id || "new"} onChange={(e) => load({ ...st, portfolio_id: e.target.value === "new" ? "" : e.target.value })}>
                {portfolios.map((p) => <option key={p.portfolio_id} value={p.portfolio_id}>{p.name}</option>)}
                <option value="new">A new portfolio...</option>
              </select></label>
            <div className="import-new" hidden={!!st.portfolio_id || undefined}>
              <input maxLength={60} placeholder="e.g. CommSec" value={newName} aria-label="New portfolio name" onChange={(e) => setNewName(e.target.value)} />
              <select aria-label="Tax type" value={taxType} onChange={(e) => setTaxType(e.target.value)}>{pf.tax_types.map((t) => <option key={t.tax_type} value={t.tax_type}>{t.label}</option>)}</select>
            </div>
            <p className="hint">Lines already in that portfolio (same code, date, units and price) are left out, so importing the same file twice adds nothing.</p>
          </Card>
        </div>
        <div className="table-wrap"><table className="grid compact import-lines">
          <thead><tr>{([["", null], ["Row", "num opt"], ["Date"], ["Code"], ["Side", "opt"], ["Units", "num"], ["Price", "num"], ["Brokerage", "num opt"], ["Status"]] as [string, string?][])
            .map(([t, cl], i) => <th key={i} scope="col" className={cl || undefined}>{t}</th>)}</tr></thead>
          <tbody>{d.lines.map((l) => {
            const [label, pill] = IMPORT_STATUS[l.status];
            return (
              <tr key={l.row} className="static">
                <td><input type="checkbox" checked={ticks.get(l.row) ?? false} disabled={l.status === "skip" || l.status === "duplicate"} aria-label={`Import row ${l.row}`}
                  onChange={(e) => setTicks(new Map(ticks).set(l.row, e.target.checked))} /></td>
                <td className="num opt">{l.row}</td><td>{l.date ? longDate(l.date) : ""}</td>
                <td className="strong">{l.code || ""}</td><td className="opt">{l.side === "SELL" ? "Sell" : l.side === "BUY" ? "Buy" : ""}</td>
                <td className="num">{l.units === null ? "" : fmt(l.units, 0)}</td><td className="num">{l.price === null ? "" : money(l.price, 3)}</td>
                <td className="num opt">{l.brokerage ? money(l.brokerage) : ""}</td>
                <td title={l.reason || ""}><span className={`pill ${pill}`}>{label}</span>{l.reason ? <div className="sub-text import-reason">{l.reason}</div> : null}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
        <div className="form-actions"><button type="button" className="btn primary" onClick={go}>Import ticked lines</button><FormMessage ref={msg2} /></div>
      </>
    );
  }
  return (
    <>
      <PageHead title="Import from a broker" sub="Your broker's export into one of your portfolios" />
      <p className="hint page-note">Download your trade history (best: exact dates for capital gains tax) or your current holdings from your broker as CSV or Excel, then choose the file. Nothing is saved until you press Import. <HelpLink id="broker-import" /></p>
      <div className="cards">
        <Card title="1. Choose the file" hint="From CommSec, Sharesies, CMC Invest, nabtrade, ANZ, Moomoo, Tiger, Interactive Brokers, eToro, Selfwealth, Stake, Superhero or a spreadsheet of your own. Only ASX shares come in; other markets are listed and skipped.">
          <label className="field"><span className="field-label">Your broker's export</span>
            <input type="file" accept=".csv,.txt,.xlsx,.xlsm" aria-label="Your broker's export" onChange={(e) => pick(e.target.files?.[0])} /></label>
          <label className="field"><span className="field-label">Broker</span>
            <select aria-label="Broker" value={st.broker} onChange={(e) => { const next = { ...st, broker: e.target.value }; if (st.content) load(next); else setSt(next); }}>
              <option value="">Work it out from the file</option>
              {brokers.map((b) => <option key={b.broker_id} value={b.broker_id}>{b.name}</option>)}
            </select></label>
          <FormMessage ref={msg} />
        </Card>
      </div>
      <div>{out}</div>
    </>
  );
}
