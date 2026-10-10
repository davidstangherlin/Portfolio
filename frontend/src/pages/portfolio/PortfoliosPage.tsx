// Portfolios: #/portfolios (or ?new=1 to start a new one), each with its own tax type.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ErrorLine, Loading, PageHead } from "../../components/bits";
import { Card } from "../../components/Card";
import { Field, FormMessage } from "../../components/forms";
import { getJSON, send } from "../../lib/api";
import { showMessage } from "../../lib/forms";
import { fmt, money, plural, signClass, signed } from "../../lib/format";
import { host } from "../../lib/host";
import { discountText, portfolioHref, type PortfolioSummary, type TaxType } from "./common";

export const TaxTag = ({ p }: { p: { tax_type_label: string; discount_rate: number } }) => <span className="tag">{`${p.tax_type_label}, ${discountText(p.discount_rate)}`}</span>;
export function TaxSelect({ types, value, onChange }: { types: TaxType[]; value: string; onChange: (v: string) => void }) {
  return (
    <select name="tax_type" value={value} onChange={(e) => onChange(e.target.value)}>
      {types.map((t) => <option key={t.tax_type} value={t.tax_type}>{`${t.tax_type === "SMSF" ? "SMSF" : t.label} (${discountText(t.discount_rate)})`}</option>)}
    </select>
  );
}

function holdingsText(p: PortfolioSummary) {
  const s = p.sections;
  const etfs = s && s.ETF ? s.ETF.holdings : 0, lics = s && s.LIC ? s.LIC.holdings : 0, shares = p.holdings - etfs - lics;
  const parts = [shares ? `${fmt(shares, 0)} ${shares === 1 ? "company" : "companies"}` : null, etfs ? plural(etfs, "ETF") : null, lics ? plural(lics, "LIC") : null].filter(Boolean);
  return `${parts.join(" and ")}, ${plural(p.open_parcels, "parcel")}`;
}
const money0 = (v: number) => money(v, 0);

function PortfolioCard({ p }: { p: PortfolioSummary }) {
  return (
    <a className="card pf-card" href={portfolioHref(p)}>
      <div className="pf-head"><h2>{p.name}</h2>{p.archived ? <span className="tag muted">Archived</span> : null}</div>
      <TaxTag p={p} />
      {p.archived ? <p className="hint">{`${plural(p.sales, "sale")} kept for tax records.`}</p>
        : !p.holdings ? <p className="hint pf-kv">No holdings yet. Open it to record a buy.</p> : (
          <dl className="kv pf-kv">
            <dt>Value</dt><dd>{money(p.value, 0)}</dd>
            <dt>Unrealised gain</dt><dd className={signClass(p.gain)}>{signed(p.gain, money0)}</dd>
            <dt>Today</dt><dd className={signClass(p.day_change)}>{signed(p.day_change, money0)}</dd>
            <dt>Holdings</dt><dd>{holdingsText(p)}</dd>
          </dl>
        )}
    </a>
  );
}

function NewPortfolioCard({ types, focus }: { types: TaxType[]; focus: boolean }) {
  const [name, setName] = useState(""), [tax, setTax] = useState("INDIVIDUAL");
  const msg = useRef<HTMLParagraphElement>(null), card = useRef<HTMLDivElement>(null), nameIn = useRef<HTMLInputElement>(null);
  useEffect(() => { if (focus) setTimeout(() => { card.current?.firstElementChild?.scrollIntoView({ block: "center" }); nameIn.current?.focus(); }, 0); }, [focus]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const p = await send<{ portfolio_id: string }>("POST", "/api/portfolios", { name, tax_type: tax });
      host().afterChange();
      location.hash = portfolioHref(p);
    } catch (err) { showMessage(msg.current, (err as Error).message, false); }
  };
  return (
    <div className="cards" style={{ marginTop: 16 }} ref={card}>
      <Card title="New portfolio" hint="One per owner or account, for example your own shares, a family trust or a self-managed super fund.">
        <form className="form-grid" noValidate onSubmit={submit}>
          <Field label="Name"><input ref={nameIn} name="name" maxLength={60} required placeholder="e.g. Super fund" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Owner's tax type" hint="Sets the capital gains tax discount on its sales."><TaxSelect types={types} value={tax} onChange={setTax} /></Field>
          <div className="form-actions"><button className="btn primary" type="submit">Create portfolio</button></div>
          <FormMessage ref={msg} />
        </form>
      </Card>
    </div>
  );
}

export function PortfoliosPage({ query }: { query?: string }) {
  const [d, setD] = useState<{ portfolios: PortfolioSummary[]; tax_types: TaxType[] } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const wantNew = new URLSearchParams(query || "").get("new") === "1";
  useEffect(() => {
    let live = true;
    getJSON<{ portfolios: PortfolioSummary[]; tax_types: TaxType[] }>("/api/portfolios")
      .then((x) => { if (live) { setD(x); if (!wantNew) window.scrollTo(0, 0); } }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, [wantNew]);
  if (error) return <ErrorLine error={error} />;
  if (!d) return <Loading text="Loading portfolios..." />;
  const active = d.portfolios.filter((p) => !p.archived), archived = d.portfolios.filter((p) => p.archived);
  return (
    <>
      <PageHead title="Portfolios" sub={active.length ? plural(active.length, "active portfolio") : null}><a className="btn" href="#/portfolios/import">Import from a broker</a></PageHead>
      {active.length ? <div className="cards">{active.map((p) => <PortfolioCard key={p.portfolio_id} p={p} />)}</div>
        : <p className="empty">No portfolios yet. Create one below, then record your first buy.</p>}
      {archived.length ? (
        <details className="archived"><summary><span className="twisty" aria-hidden="true" />{`Archived (${archived.length})`}</summary>
          <div className="cards">{archived.map((p) => <PortfolioCard key={p.portfolio_id} p={p} />)}</div></details>
      ) : null}
      <NewPortfolioCard types={d.tax_types} focus={wantNew} />
    </>
  );
}
