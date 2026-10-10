// Holdings tables and portfolio figures, shared by the dashboard and the
// portfolio pages (portfolioStrip(), sectionLine(), holdingsSections() in
// web/app.js): shares, then ETFs, then LICs, each with a subtotal.
import { Badge, ClickableRow } from "../../components/bits";
import { CautionTag, StatTile } from "../../components/common";
import { HelpTh } from "../../components/FieldHelp";
import { FilterableTable } from "../../components/FilterableTable";
import { fmt, longDate, money, pct, plural, signClass, signed, signedPct } from "../../lib/format";
import type { Field, Fields } from "../../lib/tableFilter";
import { FUNDS, fundHref, premText, PremCell, RetCell, RowTo, type Kind } from "../funds/common";

type N = number | null;
export interface HoldingLine {
  asx_code: string; company_name: string | null; security_type?: string | null; units: number; cost_base: N; price: N; value: N; gain: N; day_change: N;
  action?: string | null; short_caution?: string | null; next_discount_date: string | null; premium_now?: N; return_1y?: N; distribution_yield_12m?: N;
  [key: string]: unknown;
}
export interface Section { holdings: number; value: N; gain: N; day_change: N }
export type Sections = Partial<Record<"SHARE" | "ETF" | "LIC", Section>> | null;
export interface Totals { value: N; day_change: N; gain: N; cost_base: N; holdings: unknown[]; unpriced: unknown[] }

const money0 = (v: number) => money(v, 0);
const signedMoney = (v: N | undefined) => signed(v, money0);

export function PortfolioStrip({ pf }: { pf: Totals }) {
  const gainPct = pf.gain !== null && pf.cost_base ? (pf.gain / pf.cost_base) * 100 : null;
  const prevValue = pf.day_change !== null && pf.value !== null ? pf.value - pf.day_change : null;
  const dayPct = prevValue && pf.day_change !== null ? (pf.day_change / prevValue) * 100 : null;
  const n = pf.holdings.length;
  return (
    <div className="stats">
      <StatTile label="Portfolio value" value={money(pf.value, 0)} note={`${plural(n, "holding")}${pf.unpriced.length ? `, ${pf.unpriced.length} without a price` : ""}`} />
      <StatTile label="Today" value={signedMoney(pf.day_change)} cls={signClass(pf.day_change)} note={dayPct === null ? "needs two days of prices" : signed(dayPct, (v) => fmt(v, 2) + "%")} />
      <StatTile label="Unrealised gain" value={signedMoney(pf.gain)} cls={signClass(pf.gain)} note={gainPct === null ? null : signed(gainPct, (v) => fmt(v, 1) + "%") + " on cost"} />
      <StatTile label="Cost base" value={money(pf.cost_base, 0)} note="purchase price plus brokerage" />
    </div>
  );
}

/* "Shares $X (3) | ETFs $Y (2) | LICs $Z (1)" under a portfolio's figures. */
export function SectionLine({ sections }: { sections: Sections }) {
  if (!sections || !(["ETF", "LIC"] as const).some((k) => sections[k] && sections[k]!.holdings)) return null;
  const parts = ([["Shares", "SHARE"], ["ETFs", "ETF"], ["LICs", "LIC"]] as const).filter(([, k]) => sections[k] && sections[k]!.holdings)
    .map(([label, k]) => `${label} ${money(sections[k]!.value, 0)} (${plural(sections[k]!.holdings, "holding")})`);
  return <p className="hint section-line">{parts.join("  |  ")}</p>;
}

export function SectionHead({ title, s }: { title: string; s?: Section | null }) {
  return (
    <div className="section-head"><h2>{title}</h2>
      {s && s.holdings ? <span className="sub">{`${money(s.value, 0)} | gain ${signedMoney(s.gain)}${s.day_change !== null ? ` | today ${signedMoney(s.day_change)}` : ""}`}</span> : null}
    </div>
  );
}

/* Tables as filter fields. */
export const codeField = <R extends { asx_code: string; company_name?: string | null }>(label: string): Field<R> =>
  ({ label, type: "text", get: (r) => r.asx_code, text: (r) => `${r.asx_code} ${r.company_name || ""}` });
export const numField = <R,>(label: string, key: string, show: (v: N) => string): Field<R> =>
  ({ label, type: "num", get: (r) => (r as Record<string, unknown>)[key], text: (r) => show((r as Record<string, unknown>)[key] as N) });
const discountField: Field<HoldingLine> = { label: "CGT discount from", type: "text", get: (r) => (r.next_discount_date ? longDate(r.next_discount_date) : "eligible now") };
export function holdingFields(kind: "SHARE" | Kind): Fields<HoldingLine> {
  const base: Fields<HoldingLine> = {
    asx_code: codeField(kind === "SHARE" ? "Company" : FUNDS[kind].noun),
    units: numField("Units", "units", (v) => fmt(v, 0)),
    cost_base: numField("Cost base", "cost_base", (v) => money(v, 0)),
    price: numField(kind === "SHARE" ? "Price" : FUNDS[kind].price, "price", (v) => money(v)),
    value: numField("Value", "value", (v) => money(v, 0)),
    gain: numField("Gain", "gain", signedMoney),
    day_change: numField("Today", "day_change", signedMoney),
  };
  if (kind === "SHARE") return { ...base, action: { label: "Action", type: "text", get: (r) => r.action }, next_discount_date: discountField };
  return { ...base,
    [kind === "LIC" ? "premium_now" : "return_1y"]: kind === "LIC" ? numField("Premium/discount to NTA", "premium_now", premText) : numField("1-year return", "return_1y", (v) => signedPct(v)),
    distribution_yield_12m: numField("Yield (12 months)", "distribution_yield_12m", (v) => pct(v, 1)), next_discount_date: discountField };
}

type TP = Record<string, unknown>;
function HoldingsTable({ lines, tableProps }: { lines: HoldingLine[]; tableProps?: TP }) {
  const heads = ["Company", "Units", "Cost base", "Price", "Value", "Gain", "Today", "Action", "CGT discount from"];
  const numeric = new Set([1, 2, 3, 4, 5, 6]), optional = new Set([2, 3, 6, 8]);
  return (
    <div className="table-wrap"><table className="grid" {...tableProps}>
      <thead><tr>{heads.map((x, i) => <HelpTh key={x} label={x} tab className={[numeric.has(i) ? "num" : "", optional.has(i) ? "opt" : ""].join(" ").trim() || undefined} />)}</tr></thead>
      <tbody>{lines.map((r) => (
        <ClickableRow key={r.asx_code} code={r.asx_code}>
          <td><span className="code">{r.asx_code}</span><div className="name">{r.company_name || ""}</div></td>
          <td className="num">{fmt(r.units, 0)}</td>
          <td className="num opt">{money(r.cost_base, 0)}</td>
          <td className="num opt">{money(r.price)}</td>
          <td className="num">{money(r.value, 0)}</td>
          <td className={`num ${signClass(r.gain) || ""}`.trim()}>{signedMoney(r.gain)}</td>
          <td className={`num opt ${signClass(r.day_change) || ""}`.trim()}>{signedMoney(r.day_change)}</td>
          <td>{r.action ? <Badge action={r.action} /> : <span className="hint">not screened</span>}<CautionTag level={r.short_caution} iconOnly held /></td>
          <td className="opt">{r.next_discount_date ? longDate(r.next_discount_date) : "eligible now"}</td>
        </ClickableRow>
      ))}</tbody>
    </table></div>
  );
}

function FundHoldingsTable({ kind, lines, tableProps }: { kind: Kind; lines: HoldingLine[]; tableProps?: TP }) {
  const F = FUNDS[kind];
  const heads = [F.noun, "Units", "Cost base", F.price, "Value", "Gain", "Today", kind === "LIC" ? "Premium/discount to NTA" : "1-year return", "Yield (12 months)", "CGT discount from"];
  const numeric = new Set([1, 2, 3, 4, 5, 6, 7, 8]), optional = new Set([2, 3, 6, 8, 9]);
  return (
    <div className="table-wrap"><table className="grid" {...tableProps}>
      <thead><tr>{heads.map((x, i) => <HelpTh key={x} label={x} tab className={[numeric.has(i) ? "num" : "", optional.has(i) ? "opt" : ""].join(" ").trim() || undefined} />)}</tr></thead>
      <tbody>{lines.map((r) => (
        <RowTo key={r.asx_code} href={fundHref(kind, r.asx_code)}>
          <td><span className="code">{r.asx_code}</span><div className="name">{r.company_name || ""}</div></td>
          <td className="num">{fmt(r.units, 0)}</td>
          <td className="num opt">{money(r.cost_base, 0)}</td>
          <td className="num opt">{money(r.price)}</td>
          <td className="num">{money(r.value, 0)}</td>
          <td className={`num ${signClass(r.gain) || ""}`.trim()}>{signedMoney(r.gain)}</td>
          <td className={`num opt ${signClass(r.day_change) || ""}`.trim()}>{signedMoney(r.day_change)}</td>
          {kind === "LIC" ? <PremCell v={r.premium_now} /> : <RetCell v={r.return_1y} />}
          <td className="num opt">{pct(r.distribution_yield_12m, 1)}</td>
          <td className="opt">{r.next_discount_date ? longDate(r.next_discount_date) : "eligible now"}</td>
        </RowTo>
      ))}</tbody>
    </table></div>
  );
}

/* Shares, then ETFs, then LICs, each under its own heading with a subtotal; filterable when `filterKey` is given. */
export function HoldingsSections({ lines, sections, filterKey }: { lines: HoldingLine[]; sections: Sections; filterKey?: string }) {
  const of = (kind: string) => lines.filter((l) => (l.security_type || "SHARE") === kind);
  const table = (kind: "SHARE" | Kind, rows: HoldingLine[]) => {
    const draw = (shown: HoldingLine[], tp?: TP) => (kind === "SHARE" ? <HoldingsTable lines={shown} tableProps={tp} /> : <FundHoldingsTable kind={kind} lines={shown} tableProps={tp} />);
    if (!filterKey) return draw(rows);
    const fields = holdingFields(kind);
    return <FilterableTable filterKey={`${filterKey}:${kind}`} fields={fields} columns={Object.keys(fields)} rows={rows} render={(shown, tp) => draw(shown, tp)} />;
  };
  const block = (title: string, kind: "SHARE" | Kind, rows: HoldingLine[]) =>
    rows.length ? <><SectionHead title={title} s={sections && sections[kind]} />{table(kind, rows)}</> : null;
  return <div className="holdings-sections">{block("Shares", "SHARE", of("SHARE"))}{block("ETFs", "ETF", of("ETF"))}{block("LICs", "LIC", of("LIC"))}</div>;
}

