// Analyst ratings, price targets and holders, from Yahoo Finance (§29).
import { Legend, TableView } from "../../components/bits";
import { Card } from "../../components/Card";
import { Explained, KV, StatTile } from "../../components/common";
import { HelpLink } from "../../components/HelpLink";
import { compact, fmt, longDate, money, monthYear, NA, pct, signClass, signedPct, sum } from "../../lib/format";
import { h } from "../../lib/dom";
import { hideTip, placeTipBelow, showTip, tipRow } from "../../lib/tooltip";
import type { Company, HolderRow, Insights, Rating } from "./types";

const RATINGS: [keyof Rating, string, string][] = [
  ["strong_buy", "Strong buy", "--r-sb"], ["buy", "Buy", "--r-b"], ["hold", "Hold", "--r-h"],
  ["sell", "Sell", "--r-s"], ["strong_sell", "Strong sell", "--r-ss"]];
const CONSENSUS: Record<string, string> = { strong_buy: "Strong buy", buy: "Buy", hold: "Hold", underperform: "Underperform", sell: "Sell" };
const YAHOO_NOTE = "From Yahoo Finance, for context only: not used in Sift's estimated value, scores or signals.";
const count = (r: Rating, k: keyof Rating) => r[k] as number;

function FetchedNote({ ins, help }: { ins: Insights; help: string }) {
  return <p className="card-foot hint">{`Yahoo Finance, fetched ${longDate(ins.fetched_at.slice(0, 10))}. Refreshed weekly. `}<HelpLink id={help} /></p>;
}

function RatingRow({ r }: { r: Rating }) {
  const total = sum(RATINGS.map(([k]) => count(r, k)));
  const label = monthYear(r.rating_month);
  const tipNodes = () => [h("div", { class: "t-title", text: `${label}: ${total} analyst${total === 1 ? "" : "s"}` }),
    ...RATINGS.map(([k, name, color]) => tipRow(String(count(r, k)), name, color))];
  return (
    <div className="rating-row" tabIndex={0} aria-label={`${label}: ${RATINGS.map(([k, name]) => `${count(r, k)} ${name.toLowerCase()}`).join(", ")}`}
      onPointerMove={(e) => showTip(e, tipNodes())} onPointerLeave={hideTip}
      onFocus={(e) => placeTipBelow(e.currentTarget, tipNodes())} onBlur={hideTip}>
      <span className="rating-month">{label}</span>
      <div className="rating-bar">{RATINGS.filter(([k]) => count(r, k) > 0).map(([k, , color]) =>
        <span key={k} className="rating-seg" style={{ flexGrow: count(r, k), background: `var(${color})` }} />)}</div>
      <span className="rating-total">{String(total)}</span>
    </div>
  );
}

export function AnalystCard({ ins }: { ins: Insights | null }) {
  const title = "Analyst ratings";
  if (!ins) return <Card title={title} hint="Not fetched yet. Sift fetches analyst ratings and holders from Yahoo Finance weekly, so this fills in within a week." />;
  if (!ins.ratings.length) return <Card title={title} hint="No analyst ratings on Yahoo Finance for this company."><FetchedNote ins={ins} help="analyst-ratings" /></Card>;
  const latest = ins.ratings[ins.ratings.length - 1];
  const total = sum(RATINGS.map(([k]) => count(latest, k)));
  const consensus = ins.recommendation_key ? CONSENSUS[ins.recommendation_key] : undefined;
  return (
    <Card title={title} hint={YAHOO_NOTE}>
      <p className="consensus">{consensus ? <strong>{consensus}</strong> : null}{consensus ? " consensus" : "Consensus not given"}
        {ins.recommendation_mean ? ` (${fmt(ins.recommendation_mean, 1)} on a scale of 1 strong buy to 5 strong sell)` : ""}
        {`, ${total} analyst${total === 1 ? "" : "s"} in ${monthYear(latest.rating_month)}.`}</p>
      <Legend items={RATINGS.map(([, name, color]) => ({ name, color }))} rect />
      <div className="rating-rows">{ins.ratings.map((r) => <RatingRow key={r.rating_month} r={r} />)}</div>
      <TableView headers={["Month", ...RATINGS.map(([, name]) => name)]}
        rows={[...ins.ratings].reverse().map((r) => [monthYear(r.rating_month), ...RATINGS.map(([k]) => String(count(r, k)))])} />
      <FetchedNote ins={ins} help="analyst-ratings" />
    </Card>
  );
}

export function TargetCard({ ins, c }: { ins: Insights | null; c: Company }) {
  const title = "Analyst price targets";
  if (!ins) return null;
  if (ins.target_mean === null) return <Card title={title} hint="No price targets on Yahoo Finance for this company."><FetchedNote ins={ins} help="price-targets" /></Card>;
  const mean = ins.target_mean;
  const price = c.current_price, value = c.dcf_intrinsic_value !== null && c.dcf_intrinsic_value > 0 ? c.dcf_intrinsic_value : null;
  const vsPrice = (v: number | null) => (v && price ? ` (${signedPct(((v - price) / price) * 100)} vs price)` : "");
  const points = ([
    { name: "Share price", color: "--s1", v: price },
    { name: "Average target", color: "--s3", v: mean },
    { name: "Sift's estimated value", color: "--s2", v: value }] as { name: string; color: string; v: number | null }[]).filter((p): p is { name: string; color: string; v: number } => Boolean(p.v));
  const lo = Math.min(ins.target_low ?? mean, ...points.map((p) => p.v));
  const hi = Math.max(ins.target_high ?? mean, ...points.map((p) => p.v));
  const pad = (hi - lo) * 0.06 || hi * 0.05;
  const at = (v: number) => `${((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100}%`;
  return (
    <Card title={title} hint={`${YAHOO_NOTE} The bar spans the lowest to highest target.`}>
      <Legend items={points.map(({ name, color }) => ({ name, color }))} rect />
      <div className="target-strip" role="img" aria-label={`Targets from ${money(ins.target_low)} to ${money(ins.target_high)}. ${points.map((p) => `${p.name} ${money(p.v)}`).join(". ")}.`}>
        {ins.target_low !== null && ins.target_high !== null
          ? <span className="target-band" style={{ left: at(ins.target_low), width: `calc(${at(ins.target_high)} - ${at(ins.target_low)})` }} /> : null}
        {points.map((p) => <span key={p.name} className="target-dot" style={{ left: at(p.v), background: `var(${p.color})` }}
          onPointerMove={(e) => showTip(e, [tipRow(money(p.v), p.name, p.color)])} onPointerLeave={hideTip} />)}
        <span className="target-end lo">{money(ins.target_low)}</span>
        <span className="target-end hi">{money(ins.target_high)}</span>
      </div>
      <KV rows={[["Average target", money(mean) + vsPrice(mean)], ["Median target", money(ins.target_median)],
        ["Lowest target", money(ins.target_low)], ["Highest target", money(ins.target_high)],
        ["Analysts", String(ins.analyst_count ?? NA)], ["Sift's estimated value", value ? money(value) + vsPrice(value) : NA]]} />
      <FetchedNote ins={ins} help="price-targets" />
    </Card>
  );
}

function HolderTable({ rows }: { rows: HolderRow[] }) {
  const heads: [string, string?][] = [["Holder"], ["Shares"], ["% held", "%"], ["Value now", "Value"], ["Change", "Chg"], ["Reported"]];
  const optional = new Set([1, 5]);
  return (
    <div className="table-wrap"><table className="grid holders">
      <thead><tr>{heads.map(([x, short], i) => (
        <th key={x} className={[i ? "num" : "", optional.has(i) ? "opt" : ""].join(" ").trim() || undefined} title={x}>
          {short ? <><span className="long">{x}</span><span className="short">{short}</span></> : x}</th>
      ))}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}>
          <td className="holder-name">{r.holder}</td>
          <td className="num opt">{fmt(r.shares, 0)}</td>
          <td className="num">{pct(r.percent_held, 2)}</td>
          <td className="num">{r.value_now === null ? NA : compact(r.value_now)}</td>
          <td className={`num ${signClass(r.percent_change) || ""}`.trim()}>{r.percent_change === null ? NA : signedPct(r.percent_change)}</td>
          <td className="num opt">{r.date_reported ? longDate(r.date_reported) : NA}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

export function HoldersCard({ ins }: { ins: Insights | null }) {
  if (!ins) return null;
  const major: [string, string, string][] = [["Insiders", pct(ins.insiders_percent, 1), "of shares"], ["Institutions", pct(ins.institutions_percent, 1), "of shares"],
    ["Institutions (% of float)", pct(ins.institutions_float_percent, 1), "of shares that trade"],
    ["Number of institutions", String(ins.institutions_count ?? NA), "holding shares"]];
  const section = (label: string, rows: HolderRow[]) => (
    <>
      <h3 className="holders-head"><Explained label={label} /></h3>
      {rows.length ? <HolderTable rows={rows} /> : <p className="hint">None listed on Yahoo Finance.</p>}
    </>
  );
  return (
    <Card title="Holders" wide hint="From Yahoo Finance. Holder lists come mostly from overseas fund filings, so Australian super funds are often missing. Value now is the holding at today's price.">
      <h3 className="holders-head"><Explained label="Major holders" /></h3>
      <div className="stats">{major.map(([label, v, note]) => <StatTile key={label} label={label} value={v} note={note} />)}</div>
      {section("Top mutual fund holders", ins.funds)}
      {section("Top institutional holders", ins.institutions)}
      <FetchedNote ins={ins} help="major-holders" />
    </Card>
  );
}
