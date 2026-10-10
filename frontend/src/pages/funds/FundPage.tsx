// One ETF or LIC: #/etf/{code} or #/lic/{code}, with ?compare={code} for the
// reference fund. Changing the comparison keeps the page in place.
import { Fragment, useEffect, useState } from "react";
import { columnChart } from "../../charts/columnChart";
import { dividendMarkers, lineChart, type Point } from "../../charts/lineChart";
import { Loading, TableView } from "../../components/bits";
import { Card } from "../../components/Card";
import { ChartSlot } from "../../components/ChartSlot";
import { BackLink, Explained, StatTile } from "../../components/common";
import { useFieldHelp } from "../../components/FieldHelp";
import { HelpLink } from "../../components/HelpLink";
import { WatchButton, WatchNote, type WatchEntry } from "../../components/watch";
import { getJSON } from "../../lib/api";
import { compact, fmt, longDate, money, monthYear, NA, pct, signClass, signedPct, toDate } from "../../lib/format";
import { host } from "../../lib/host";
import { hideTip } from "../../lib/tooltip";
import { AboutCompany } from "../company/CompanyPage";
import { FUNDS, fundHref, fundSize, monthName, premText, RetCell, type FundRow, type Kind } from "./common";
import { FundHoldingsCard, type Profile } from "./holdings";

type N = number | null;
interface Fund extends FundRow {
  current_price: N; price_date: string | null; day_change_percent: N; mer_percent: N; performance_fee: string | null; fum_aud: N;
  net_flows_aud: N; distribution_yield_12m: N; distributions_12m: N; premium_now: N; nta_pre_tax: N; nta_date: string | null; nta_premium_percent: N;
  benchmark: string | null; fund_of_funds: boolean | null; report_month: string | null; sub_category: string | null; listing_date: string | null;
  distribution_frequency: string | null; avg_spread_percent: N; value_traded_aud: N; first_price_date: string | null;
  report_flags: Record<string, string> | null; report_checks: Record<string, unknown> | null; check_month: string | null;
}
interface Peer { median: N; rank: number | null; of: number; ordinal: string }
interface FundData {
  etf: Fund; reference: Fund | null; reference_options: { asx_code: string; company_name: string | null; category: string }[];
  peers: Record<string, Peer> | null; index: { name: string; month: string; periods: { key: string; fund: N; index: N; difference: N }[] } | null;
  growth: { etf: Point[]; reference: Point[] }; prices: Point[]; distributions: [string, number][];
  recent_distributions: { ex_date: string; amount: number }[]; distributions_by_year: { financial_year: string; amount: number | null; partial: boolean }[];
  monthly: { report_month: string; fum_aud: N; mer_percent: N; nta_pre_tax: N; nta_date: string | null; nta_premium_percent: N }[];
  position: { units: number; cost_base: number } | null; watchlists: WatchEntry[]; profile: Profile | null;
}

/* ---------- performance (§26.1) ---------- */
const PERF_YEARLY: [string, string][] = [["return_1y", "1 year"], ["return_3y", "3 years"], ["return_5y", "5 years"], ["return_10y", "10 years"]];
const PERF_RECENT: [string, string][] = [["return_1m", "1 month"], ["return_3m", "3 months"], ["return_6m", "6 months"]];
const SINCE = "return_since_inception";
const flagOf = (row: Fund | null, k: string) => (row && row.report_flags ? row.report_flags[k] : null);
const val = (row: Fund | null, k: string) => (row ? (row[k] as N) : null);
const sinceDate = (iso: string) => toDate(iso).toLocaleDateString("en-AU", { month: "short", year: "numeric" });
const shortName = (label: string) => label.replace(" months", "m").replace(" month", "m").replace(" years", "y").replace(" year", "y");

function PerfCell({ row, k, note }: { row: Fund | null; k: string; note?: string | null }) {
  const v = val(row, k), flag = flagOf(row, k);
  return (
    <td className={`num ${flag ? "flagged" : signClass(v) || ""}`.trim()} title={flag ? `Check: ${flag}.` : undefined}>
      {signedPct(v)}{flag ? <span className="flag" aria-label={`check: ${flag}`}> ⚠</span> : null}
      {note ? <div className="cell-note">{note}</div> : null}
    </td>
  );
}
/* Where the rank sits, by the share of the other funds that did better; none for under five funds. */
const rankBand = (rank: number, of: number) => {
  if (of < 5) return "";
  const f = (rank - 1) / (of - 1);
  return f <= 0.1 ? "top 10%" : f <= 0.25 ? "top quarter" : f <= 0.5 ? "top half" : f <= 0.75 ? "bottom half" : "bottom quarter";
};
function RankCell({ p }: { p: Peer | undefined }) {
  if (!p || !p.rank) return <td className="num muted">{NA}</td>;
  return (
    <td className="num"><span className="long">{`${p.ordinal} of ${p.of}`}{rankBand(p.rank, p.of) ? <div className="cell-note">{rankBand(p.rank, p.of)}</div> : null}</span>
      <span className="short">{`${p.ordinal}/${p.of}`}</span></td>
  );
}
function HelpHeadTh({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  const { props, info } = useFieldHelp(label);
  const cls = [className, (props as { className?: string }).className].filter(Boolean).join(" ") || undefined;
  return <th {...props} className={cls} tabIndex={0}>{children}{info}</th>;
}
const LongShort = ({ long, short }: { long: string; short?: string }) => (short ? <><span className="long">{long}</span><span className="short">{short}</span></> : <>{long}</>);

/* The fund against its market index, both from the ASX report (§26.2). */
function IndexTable({ d }: { d: FundData }) {
  const x = d.index, code = d.etf.asx_code;
  if (!x) return null;
  const label = (k: string) => [...PERF_YEARLY, ...PERF_RECENT].find(([key]) => key === k)![1];
  return (
    <div className="index-block">
      <h3 className="holders-head"><Explained label="Against its index" /><span className="hint">{` to the end of ${monthName(x.month)}, both from the ASX report and both counting franking credits`}</span></h3>
      <div className="table-wrap"><table className="grid compact perf-table">
        <thead><tr><th>Period</th>{([[code], [x.name, "Index"], ["Difference", "Diff"]] as [string, string?][]).map(([t, short]) => <th key={t} className="num"><LongShort long={t} short={short} /></th>)}</tr></thead>
        <tbody>{x.periods.map((p) => {
          const yearly = /_(3y|5y|10y)$/.test(p.key), diff = signedPct(p.difference).replace("%", "");
          return (
            <tr key={p.key} className="static">
              <td><span className="long">{label(p.key) + (yearly ? " (a year)" : "")}</span><span className="short">{shortName(label(p.key))}</span></td>
              <RetCell v={p.fund} /><RetCell v={p.index} />
              <td className={`num ${signClass(p.difference) || ""}`.trim()}><span className="long">{`${diff} points`}</span><span className="short">{diff}</span></td>
            </tr>
          );
        })}</tbody>
      </table></div>
    </div>
  );
}

function PerformanceCard({ d, kind, onCompare }: { d: FundData; kind: Kind; onCompare: (code: string) => void }) {
  const F = FUNDS[kind], e = d.etf, peers = d.peers || {}, ref = d.reference;
  const flaggedHere = (k: string) => flagOf(e, k) || flagOf(ref, k);
  const cats = PERF_YEARLY.map(([k, label]) => (flaggedHere(k) ? `${label} ⚠` : label));
  const yearly = (row: Fund | null) => PERF_YEARLY.map(([k]) => (row && !flagOf(row, k) ? val(row, k) : null));
  const median = (k: string) => (peers[k] ? peers[k].median : null);
  const series = [{ name: e.asx_code, color: "--s1", values: yearly(e) }, { name: `${e.category} median`, color: "--s2", values: PERF_YEARLY.map(([k]) => median(k)) }];
  if (ref) series.push({ name: ref.asx_code, color: "--s3", values: yearly(ref) });
  const heads = ["Period", e.asx_code, ref ? ref.asx_code : "Reference fund", "Category median", "Rank in category"];
  const line = (k: string, label: string) => (
    <tr key={k} className="static">
      <td><span className="long">{label}</span><span className="short">{shortName(label)}</span></td>
      <PerfCell row={e} k={k} /><PerfCell row={ref} k={k} /><RetCell v={median(k)} cls="ph-hide" /><RankCell p={peers[k]} />
    </tr>
  );
  const group = (text: string) => <tr className="static group-row"><td colSpan={5}>{text}</td></tr>;
  const checks = ([[e, e.asx_code], [ref, ref && ref.asx_code]] as [Fund | null, string | null][]).flatMap(([row, code]) => row && row.report_flags
    ? [...PERF_YEARLY, ...PERF_RECENT, [SINCE, "Since first price"]].filter(([k]) => row.report_flags![k])
      .map(([k, label]) => `${code} ${label.toLowerCase()}: ${row.report_flags![k]}.`) : []);
  const checked = e.report_checks && Object.keys(e.report_checks).length;
  const same = d.reference_options.filter((o) => o.category === e.category), other = d.reference_options.filter((o) => o.category !== e.category);
  const opt = (o: { asx_code: string; company_name: string | null }) => <option key={o.asx_code} value={o.asx_code}>{`${o.asx_code} ${o.company_name || ""}`}</option>;
  return (
    <Card title="Performance" wide hint={`Total return with ${F.payouts.toLowerCase()} reinvested, as a yearly rate.`}>
      <div className="compare-row"><label>Compare with </label>
        <select aria-label="Reference fund" value={ref ? ref.asx_code : ""} onChange={(ev) => onCompare(ev.target.value)}>
          {same.length ? <optgroup label={e.category}>{same.map(opt)}</optgroup> : null}
          {other.length ? <optgroup label={`Other ${F.nouns}`}>{other.map(opt)}</optgroup> : null}
        </select>{" "}<HelpLink id="reference-fund" /></div>
      {checks.length ? (
        <div className="hint note"><strong>⚠ Figures to check. </strong>
          {`Left off the chart and the category median and rank. ${kind === "LIC" ? "" : "The ASX counts franking credits, so a franked Australian fund's ASX figure runs a little higher. "}`}
          <ul className="check-list">{checks.map((t) => <li key={t}>{t}</li>)}</ul><HelpLink id="asx-report-check" /></div>
      ) : checked ? (
        <p className="check-ok"><span className="tick" aria-hidden="true">✓ </span>{`${e.asx_code}'s figures match the ASX report to the end of ${monthName(e.check_month as string)}. `}<HelpLink id="asx-report-check" /></p>
      ) : null}
      {series.some((sr) => sr.values.some((v) => v !== null && v !== undefined))
        ? <ChartSlot draw={(w) => columnChart({ categories: cats, series, yFmt: (v) => fmt(v, Number.isInteger(v) ? 0 : 1) + "%", label: `${e.asx_code} total return, % a year`, width: w })} />
        : <p className="empty">{`No yearly figures to chart for ${e.asx_code}${ref ? ` or ${ref.asx_code}` : ""}: they're too new or need checking (see the table).`}</p>}
      <p className="recent-row"><span className="recent-label">Recent performance, not annualised:</span>
        {PERF_RECENT.map(([k, label]) => <span key={k} className="recent-item">{`${label} `}<strong className={signClass(val(e, k))}>{signedPct(val(e, k))}</strong>{flagOf(e, k) ? " ⚠" : ""}</span>)}</p>
      <div className="table-wrap"><table className="grid compact perf-table">
        <thead><tr>{heads.map((x, i) => {
          const short = ({ "Category median": "Median", "Rank in category": "Rank" } as Record<string, string>)[x];
          const cls = [i ? "num" : "", i === 3 ? "ph-hide" : ""].join(" ").trim() || undefined;
          const inner = <LongShort long={x} short={short} />;
          return i === 2 ? <HelpHeadTh key={i} label="Reference fund" className={cls}>{inner}</HelpHeadTh>
            : i >= 3 ? <HelpHeadTh key={i} label={x} className={cls}>{inner}</HelpHeadTh>
            : <th key={i} className={cls} tabIndex={0}>{inner}</th>;
        })}</tr></thead>
        <tbody>
          {group("A year (yearly rate)")}{PERF_YEARLY.map(([k, label]) => line(k, label))}
          {group("Recent (not annualised)")}{PERF_RECENT.map(([k, label]) => line(k, label))}
          {group("Since first price (a year)")}
          <tr className="static">
            <td><span className="long">Since first price</span><span className="short">Start</span></td>
            <PerfCell row={e} k={SINCE} note={e.first_price_date ? `from ${sinceDate(e.first_price_date)}` : null} />
            <PerfCell row={ref} k={SINCE} note={ref && ref.first_price_date ? `from ${sinceDate(ref.first_price_date)}` : null} />
            <td className="num muted ph-hide" title="Not compared: funds in a category start on different dates.">{NA}</td>
            <td className="num muted">{NA}</td>
          </tr>
        </tbody>
      </table></div>
      {peers.return_1y ? <p className="hint">{`Rank and median: among the ${F.nouns} in ${e.category} with a figure for each period that passed its checks. `}<HelpLink id="category-average" /></p> : null}
      <IndexTable d={d} />
    </Card>
  );
}

/* ---------- growth of $10,000 ---------- */
const GROWTH_PERIODS: [string, string, number | null][] = [["1y", "1 year", 12], ["3y", "3 years", 36], ["5y", "5 years", 60], ["10y", "10 years", 120], ["max", "All", null]];
let rememberedPeriod = "5y";
function monthsBefore(iso: string, months: number) { const d = toDate(iso); d.setMonth(d.getMonth() - months); return d.toISOString().slice(0, 10); }
/* Each series from the first date both have, rebased to $10,000. */
function growthSeries(g: FundData["growth"], ref: Fund | null, period: string) {
  const months = GROWTH_PERIODS.find((p) => p[0] === period)![2];
  const end = g.etf.length ? g.etf[g.etf.length - 1][0] : null;
  if (!end) return null;
  let start = months ? monthsBefore(end, months) : g.etf[0][0];
  if (start < g.etf[0][0]) start = g.etf[0][0];
  const refPts = ref && g.reference.length ? g.reference : null;
  let limitedBy: string | null = start > (months ? monthsBefore(end, months) : g.etf[0][0]) ? "etf" : null;
  if (refPts && refPts[0][0] > start) { start = refPts[0][0]; limitedBy = "reference"; }
  const cut = (pts: Point[]): Point[] | null => {
    const inside = pts.filter((p) => p[0] >= start && p[0] <= end);
    if (inside.length < 2) return null;
    const base = inside[0][1];
    return inside.map((p) => [p[0], (p[1] / base) * 10000]);
  };
  return { start, limitedBy, etf: cut(g.etf), reference: refPts ? cut(refPts) : null };
}
function GrowthCard({ d, kind }: { d: FundData; kind: Kind }) {
  const F = FUNDS[kind], e = d.etf, ref = d.reference;
  const [period, setPeriodState] = useState(rememberedPeriod);
  const setPeriod = (p: string) => { rememberedPeriod = p; setPeriodState(p); };
  const g = growthSeries(d.growth, ref, period);
  let body;
  if (!g || !g.etf) body = <p className="empty">Not enough price history for this period.</p>;
  else {
    const etf = g.etf, gref = g.reference;
    const series = [{ name: e.asx_code, color: "--s1", points: etf }];
    if (gref && ref) series.push({ name: ref.asx_code, color: "--s3", points: gref });
    const last = (pts: Point[]) => pts[pts.length - 1][1];
    const why = g.limitedBy === "reference" && ref ? ` (when ${ref.asx_code}'s prices start; pick another to compare over longer)`
      : g.limitedBy === "etf" && period !== "max" ? ` (when ${e.asx_code}'s prices start)` : "";
    body = (
      <>
        <p className="hint">{`$10,000 invested ${longDate(g.start)}${why}, ${F.payouts.toLowerCase()} reinvested: ${e.asx_code} now ${money(last(etf), 0)}` +
          (gref && ref ? `, ${ref.asx_code} ${money(last(gref), 0)}.` : ".")}</p>
        <ChartSlot draw={(w) => lineChart({ series, yFmt: (v) => compact(v), label: `Growth of $10,000 in ${e.asx_code}`, width: w, height: 240 })} />
        <TableView headers={["Date", e.asx_code, ref ? ref.asx_code : ""]} rows={etf.filter((_, i) => i % 13 === 0 || i === etf.length - 1).reverse()
          .map((p) => [longDate(p[0]), money(p[1], 0), gref ? money((gref.find((q) => q[0] === p[0]) || [null, null])[1], 0) : ""])} />
      </>
    );
  }
  return (
    <Card title="Growth of $10,000" wide>
      <div className="segmented periods" role="group" aria-label="Period">
        {GROWTH_PERIODS.map(([key, label]) => <button key={key} type="button" data-period={key} aria-pressed={key === period} onClick={() => setPeriod(key)}>{label}</button>)}
      </div>
      <div>{body}</div>
    </Card>
  );
}

function PriceCard({ d, kind }: { d: FundData; kind: Kind }) {
  const F = FUNDS[kind], e = d.etf, title = `${F.price}, last 12 months`;
  if (d.prices.length < 2) return <Card title={title} hint="Not enough price history yet." />;
  const markers = dividendMarkers(d.prices, d.distributions.map(([ex, amount]) => ({ ex_date: ex, amount, kind: F.payout, per: F.per })));
  return (
    <Card title={title} wide hint={`D marks each ${F.payout.toLowerCase()}'s ex-date, when the price drops by roughly the amount paid.`}>
      <ChartSlot draw={(w) => lineChart({ series: [{ name: "Close", color: "--s1", points: d.prices }], yFmt: (v) => money(v), label: `${e.asx_code} closing price`, width: w, height: 240, markers })} />
      <TableView headers={["Date", "Close"]} rows={d.prices.slice(-30).reverse().map((p) => [longDate(p[0]), money(p[1])])} />
    </Card>
  );
}

function DistributionsCard({ d, kind }: { d: FundData; kind: Kind }) {
  const F = FUNDS[kind], years = d.distributions_by_year;
  if (!years.length || !years.some((y) => y.amount)) return <Card title={F.payouts} hint={`No ${F.payouts.toLowerCase()} recorded.`} />;
  return (
    <Card title={`${F.payouts} per ${F.per}`} hint={`Cash paid per ${F.per} in each financial year (July to June), before franking. The current year is so far.`}>
      <ChartSlot draw={(w) => columnChart({ categories: years.map((y) => y.financial_year + (y.partial ? "*" : "")), yFmt: (v) => money(v),
        label: `${F.payouts} per ${F.per} by financial year`, width: w, series: [{ name: `${F.payout} per ${F.per}`, color: "--s1", values: years.map((y) => y.amount) }] })} />
      <TableView headers={["Ex-date", `Amount per ${F.per}`]} rows={d.recent_distributions.map((x) => [longDate(x.ex_date), money(x.amount, 4)])} />
    </Card>
  );
}

/* LICs: the share price against NTA at each month's NTA date. */
function NtaCard({ d }: { d: FundData }) {
  const pts: Point[] = d.monthly.filter((m) => m.nta_premium_percent !== null).map((m) => [m.nta_date || m.report_month, m.nta_premium_percent as number]);
  const e = d.etf;
  if (pts.length < 2) {
    return <Card title="Premium/discount to NTA over time"><p className="hint">{`${premText(e.nta_premium_percent)} at the last NTA date${e.nta_date ? ` (${longDate(e.nta_date)})` : ""}. ` +
      "The history builds as each month's ASX report is loaded."}</p></Card>;
  }
  return (
    <Card title="Premium/discount to NTA over time" hint="At each month's NTA date. The pink line is 0%, where the price equals NTA; below it, a discount.">
      <ChartSlot draw={(w) => lineChart({ series: [{ name: "Premium/discount", color: "--s1", points: pts }], yFmt: (v) => fmt(v, 0) + "%", zeroLine: true, label: "Premium or discount to NTA by month", width: w })} />
      <TableView headers={["NTA date", "NTA", "Premium/discount"]} rows={d.monthly.slice().reverse().map((m) => [m.nta_date ? longDate(m.nta_date) : monthYear(m.report_month), money(m.nta_pre_tax, 3), premText(m.nta_premium_percent)])} />
    </Card>
  );
}

function SizeCard({ d, kind }: { d: FundData; kind: Kind }) {
  const F = FUNDS[kind], pts: Point[] = d.monthly.filter((m) => m.fum_aud !== null).map((m) => [m.report_month, m.fum_aud as number]);
  if (pts.length < 2) return null;
  return (
    <Card title={`${F.size} over time`} hint={`${kind === "LIC" ? "Market capitalisation" : "Funds under management"} at each month end, from the ASX report.`}>
      <ChartSlot draw={(w) => lineChart({ series: [{ name: F.size, color: "--s1", points: pts }], yFmt: (v) => compact(v), label: `${F.size} by month`, width: w })} />
      <TableView headers={["Month", F.size, "Fee"]} rows={d.monthly.slice().reverse().map((m) => [monthYear(m.report_month), fundSize(m.fum_aud), pct(m.mer_percent, 2)])} />
    </Card>
  );
}

function FactDt({ k }: { k: string }) {
  return host().fieldHelp(k) ? <Explained as="dt" label={k} /> : <dt>{k}</dt>;
}
function FactsCard({ e, kind }: { e: Fund; kind: Kind }) {
  const lic = kind === "LIC";
  const items: [string, string | null][] = lic
    ? [["Type", e.product_type === "LIT" ? "Listed investment trust (LIT)" : "Listed investment company (LIC)"], ["Category", e.category],
      ["NTA (pre-tax)", e.nta_pre_tax !== null ? `${money(e.nta_pre_tax, 3)}${e.nta_date ? ` at ${longDate(e.nta_date)}` : ""}` : null],
      ["Premium/discount to NTA", e.nta_premium_percent !== null ? `${premText(e.nta_premium_percent)} at the NTA date; ${premText(e.premium_now)} at the latest price` : null],
      ["Performance fee", e.performance_fee], ["Market cap", e.fum_aud !== null ? fundSize(e.fum_aud) : null],
      ["Value traded (month)", e.value_traded_aud !== null ? fundSize(e.value_traded_aud) : null],
      ["Prices from", e.first_price_date ? longDate(e.first_price_date) : null]]
    : [["Issuer", e.issuer], ["Product type", e.product_type], ["Category", e.category], ["Sub-category", e.sub_category],
      ["Benchmark", e.benchmark], ["Listed", e.listing_date ? longDate(e.listing_date) : null],
      ["Distribution frequency", e.distribution_frequency], ["Spread", e.avg_spread_percent !== null ? pct(e.avg_spread_percent, 2) : null],
      ["Value traded (month)", e.value_traded_aud !== null ? fundSize(e.value_traded_aud) : null],
      ["Net flows", e.net_flows_aud !== null ? (e.net_flows_aud > 0 ? "+" : "") + compact(e.net_flows_aud) : null],
      ["Prices from", e.first_price_date ? longDate(e.first_price_date) : null]];
  return (
    <Card title={lic ? "Company facts" : "Fund facts"} hint={e.report_month ? `From the ASX report for ${monthName(e.report_month)}, except prices.` : "Prices only: no ASX report loaded yet."}>
      <dl className="kv">{items.filter(([, v]) => v).map(([k, v]) => <Fragment key={k}><FactDt k={k} /><dd>{v}</dd></Fragment>)}</dl>
    </Card>
  );
}

function FundBody({ d, kind, onCompare }: { d: FundData; kind: Kind; onCompare: (code: string) => void }) {
  const F = FUNDS[kind], e = d.etf;
  const [lists, setLists] = useState<WatchEntry[]>(d.watchlists);
  useEffect(() => setLists(d.watchlists), [d]);
  const yieldNote = e.distributions_12m !== null ? `${money(e.distributions_12m, 3)} per ${F.per} in 12 months` : `no ${F.payouts.toLowerCase()} in 12 months`;
  const priceTile = <StatTile label={F.price} value={money(e.current_price)} note={e.price_date ? `as at ${longDate(e.price_date)}${e.day_change_percent !== null ? `, ${signedPct(e.day_change_percent, 2)} on the day` : ""}` : null} />;
  const feeTile = <StatTile label="Fee" value={pct(e.mer_percent, 2)} note={kind === "LIC" && e.performance_fee
    ? `performance fee: ${e.performance_fee.toLowerCase()}` : e.mer_percent !== null ? `${money(e.mer_percent * 100, 0)} a year on $10,000` : "not in the ASX report"} />;
  const yieldTile = <StatTile label="Yield (12 months)" value={pct(e.distribution_yield_12m, 1)} note={yieldNote} />;
  const sub = kind === "LIC"
    ? [e.product_type === "LIT" ? "Listed investment trust" : "Listed investment company", e.fum_aud !== null ? `market cap ${fundSize(e.fum_aud)}` : null]
    : ["ETF", e.issuer, e.product_type !== "ETF" ? e.product_type : null, e.benchmark ? `tracks ${e.benchmark}` : null, e.fund_of_funds ? "invests in other ETFs" : null];
  return (
    <>
      <BackLink fallback={F.list} />
      <div className="co-head">
        <h1>{e.company_name || e.asx_code}</h1>
        <span className="ticker mono">{e.asx_code}</span>
        <span className="tag">{e.category}</span>
        <WatchButton code={e.asx_code} lists={lists} onChange={setLists} />
      </div>
      <p className="co-sub">{sub.filter(Boolean).join("  |  ")}</p>
      {d.profile && d.profile.description ? <AboutCompany c={{ business_summary: d.profile.description, business_summary_short: d.profile.description_short }} /> : null}
      <div className="stats">
        {kind === "LIC" ? <>{priceTile}<StatTile label="Premium/discount to NTA" value={premText(e.premium_now)}
          note={e.nta_pre_tax !== null ? `against NTA ${money(e.nta_pre_tax, 3)}${e.nta_date ? ` at ${longDate(e.nta_date)}` : ""}` : "no NTA in the ASX report"} />{feeTile}{yieldTile}</>
          : <>{priceTile}{feeTile}<StatTile label="Fund size" value={fundSize(e.fum_aud)} note={e.net_flows_aud !== null ? `${e.net_flows_aud > 0 ? "+" : ""}${compact(e.net_flows_aud)} net flows last month` : null} />{yieldTile}</>}
      </div>
      {d.position ? <p className="hint">{`You hold ${fmt(d.position.units, 0)} ${kind === "LIC" ? "shares" : "units"}, cost base ${money(d.position.cost_base)}` +
        (e.current_price ? `, worth ${money(d.position.units * e.current_price, 0)}.` : ".")}</p> : null}
      <WatchNote lists={lists} />
      <div className="cards">
        <PerformanceCard d={d} kind={kind} onCompare={onCompare} />
        <FundHoldingsCard p={d.profile} lic={kind === "LIC"} code={e.asx_code} />
        <GrowthCard d={d} kind={kind} />
        <PriceCard d={d} kind={kind} />
        {kind === "LIC" ? <NtaCard d={d} /> : null}
        <DistributionsCard d={d} kind={kind} />
        <FactsCard e={e} kind={kind} />
        <SizeCard d={d} kind={kind} />
      </div>
    </>
  );
}

export function FundPage({ kind, code, query }: { kind: Kind; code: string; query?: string }) {
  const F = FUNDS[kind];
  const compare = new URLSearchParams(query || "").get("compare");
  const [d, setD] = useState<FundData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    hideTip();
    let live = true;
    if (!query) setD(null);  // a new comparison keeps the page on screen until the answer arrives
    getJSON<FundData>(`/api/${F.api}/${encodeURIComponent(code)}${compare ? `?compare=${encodeURIComponent(compare)}` : ""}`)
      .then((x) => { if (live) { setD(x); setError(null); if (!query) window.scrollTo(0, 0); } }, (e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [F.api, code, compare, query]);
  if (error) return <><BackLink fallback={F.list} /><p className="error">{error}</p></>;
  if (!d) return <Loading text={`Loading ${code}...`} />;
  return <FundBody d={d} kind={kind} onCompare={(x) => { location.hash = `${fundHref(kind, d.etf.asx_code)}?compare=${x}`; }} />;
}
