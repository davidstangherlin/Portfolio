// A company's page: #/company/{code}. The same cards, words and charts as
// renderCompany() in web/app.js had, now in React (ADR-018).
import { useEffect, useState } from "react";
import { columnChart } from "../../charts/columnChart";
import { aheadRange, dividendMarkers, dividendText, lineChart, pastYears, YEAR_MS, type Point } from "../../charts/lineChart";
import { valuationBars } from "../../charts/valuationBars";
import { volumeChart } from "../../charts/volumeChart";
import { wheel } from "../../charts/wheel";
import { Badge, Loading, TableView } from "../../components/bits";
import { Card } from "../../components/Card";
import { ChartSlot } from "../../components/ChartSlot";
import { BackLink, CautionTag, KV, PassList, StatTile, ValuationPill, valuationStatus } from "../../components/common";
import { HelpLink } from "../../components/HelpLink";
import { WatchButton, WatchNote, type WatchEntry } from "../../components/watch";
import { WorkedOut } from "../../components/WorkedOut";
import { FinancialHealthCard } from "../../islands/FinancialHealthCard";
import { getJSON } from "../../lib/api";
import { compact, fmt, longDate, money, NA, pct, signClass, sum, toDate } from "../../lib/format";
import { host } from "../../lib/host";
import { hideTip } from "../../lib/tooltip";
import { AnalystCard, HoldersCard, TargetCard } from "./insights";
import { ChancesBlock, DrpCard, NoticesCard, RegistryCard, ShortSellingCard, WorkingsCard } from "./cards";
import type { Company, CompanyData, Report } from "./types";

function movingAverage(points: Point[], window = 200): Point[] {
  const out: Point[] = [];
  let run = 0;
  points.forEach((p, i) => {
    run += p[1];
    if (i >= window) run -= points[i - window][1];
    if (i >= window - 1) out.push([p[0], run / window]);
  });
  return out;
}

/* "USD, converted to AUD at 1.5234 (30 Jun 2025)" for the latest report. */
function accountsCurrency(c: Company, reports: Report[]): string {
  const latest = reports.length ? reports[reports.length - 1] : null;
  const from = (latest && latest.reporting_currency) || c.financial_currency;
  const to = c.trading_currency || "AUD";
  if (!from) return NA;
  if (from === to || !latest || !latest.fx_rate || latest.fx_rate === 1) return `${from} (no conversion needed)`;
  return `${from}, converted to ${to} at ${fmt(latest.fx_rate, 4)} (${longDate(latest.report_date)})`;
}

/* The four headline figures at the top of a company page. */
function SummaryStrip({ c, model }: { c: Company; model: CompanyData["model"] }) {
  const mos = c.margin_of_safety_percent;
  const value = c.dcf_intrinsic_value;
  const upside = value && value > 0 && c.current_price ? ((value - c.current_price) / c.current_price) * 100 : null;
  const signed = (v: number | null, dp: number) => (v === null || v === undefined ? NA : `${v > 0 ? "+" : ""}${fmt(v, dp)}%`);
  return (
    <div className="stats">
      <StatTile label="Share price" value={money(c.current_price)} note={`as at ${longDate(c.as_of_date)}`} />
      <StatTile label="Estimated value" value={value && value > 0 ? money(value) : NA} cls="accent" note={model ? `${model.method} model` : "no model could run"} />
      <StatTile label="Margin of safety" value={signed(mos, 1)} cls={signClass(mos)} note={valuationStatus(mos).label} />
      <StatTile label="Implied upside" value={signed(upside, 1)} cls={signClass(upside)} note="price to reach estimated value" />
    </div>
  );
}

function ModelNote({ model }: { model: CompanyData["model"] }) {
  if (!model) return null;
  const name = model.method === "DDM" ? "Two-stage dividend discount model (used for banks, insurers and REITs)" : "Two-stage discounted cash flow model";
  const base = model.method === "DDM" ? "average dividend per share" : "average free cash flow";
  return <p className="model-note">{`${name}: ${base} over three years, grown ${fmt(model.growth_rate * 100, 0)}% a year for ${model.stage1_years} years, ` +
    `then ${fmt(model.terminal_growth_rate * 100, 1)}% a year, discounted at ${fmt(model.discount_rate * 100, 0)}% a year.`}</p>;
}

/* What the company does: the first two sentences of Yahoo's business summary, with "more" to read the rest. */
function AboutCompany({ c }: { c: Company }) {
  const [open, setOpen] = useState(false);
  if (!c.business_summary) return null;
  const short = c.business_summary_short || c.business_summary;
  if (short === c.business_summary) return <p className="co-about"><span>{short}</span></p>;
  return <p className="co-about"><span>{open ? c.business_summary : short}</span>{" "}
    <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "less" : "more"}</button></p>;
}

/* Each spoke collapses to one line that keeps its score; closed by default. */
function Breakdown({ d }: { d: CompanyData }) {
  const [open, setOpen] = useState<boolean[]>(() => d.axes.map(() => false));
  const all = open.every(Boolean);
  return (
    <Card title="Score breakdown" hint="Six yes/no checks per spoke. No data never counts as a pass. Click a spoke to see its checks.">
      <button type="button" className="link-btn" onClick={() => setOpen(d.axes.map(() => !all))}>{all ? "Collapse all" : "Expand all"}</button>
      {d.axes.map((a, i) => (
        <details key={a} className="axis-block" open={open[i]}
          onToggle={(e) => { const now = (e.currentTarget as HTMLDetailsElement).open; setOpen((o) => (o[i] === now ? o : o.map((x, k) => (k === i ? now : x)))); }}>
          <summary><span className="twisty" aria-hidden="true" /><span className="axis-name">{a}</span><span className="axis-score">{`${d.scores[a].score} / ${d.checks_per_axis}`}</span></summary>
          <PassList items={d.scores[a].checks} />
        </details>
      ))}
    </Card>
  );
}

function Markers({ c, flags }: { c: Company; flags: string[] }) {
  const rows: [string, string][] = [
    ["Earnings quality", `${c.earnings_quality || NA}${c.cash_conversion !== null ? ` (cash flow ${fmt(c.cash_conversion, 0)}% of profit)` : ""}`],
    ["Price signal", `${c.price_signal || NA}${c.price_vs_200d !== null ? ` (${fmt(c.price_vs_200d, 1)}% vs 200-day average)` : ""}`],
    ["Dividend trend", c.dividend_trend || NA],
    ["Fundamentals trend", c.fundamentals_trend || NA],
    ["Margin of safety trend", c.margin_of_safety_trend === null ? "needs 30 days of history" : `${fmt(c.margin_of_safety_trend, 1)} points over 30 days`],
    ["Value-trap risk", c.trap_risk === "Y" ? "Yes" : "No"],
    ["Data confidence", c.data_confidence || NA]];
  return (
    <Card title="Quality and trend markers">
      <KV rows={rows} help />
      {flags.length ? <><p className="hint" style={{ marginTop: 10 }}>Red flags</p><ul className="flags">{flags.map((f) => <li key={f}>{f}</li>)}</ul></> : null}
    </Card>
  );
}

function PriceCard({ c, d }: { c: Company; d: CompanyData }) {
  if (d.prices.length < 2) return <Card title="Share price, last 12 months" hint="Not enough price history yet." wide />;
  const ma = movingAverage(d.prices);
  const series = [{ name: "Close", color: "--s1", points: d.prices }];
  if (ma.length >= 2) series.push({ name: "200-day average", color: "--s2", points: ma });
  const markers = dividendMarkers(d.prices, d.dividends || []);
  // Data table: the last 30 trading days plus every ex-dividend day in the year.
  const closeOn = new Map(d.prices.map((p) => [p[0], p[1]]));
  const divOn = new Map(markers.map((mk) => [mk.date, mk]));
  const volumes = d.volumes || [];
  const volOn = new Map(volumes.map((p) => [p[0], p[1]]));
  const rowDates = [...new Set([...d.prices.slice(-30).map((p) => p[0]), ...markers.map((mk) => mk.date)])].sort().reverse();
  // The year ahead: the likely range from the nightly statistics (docs/kb/features/statistics.md)
  const st = d.statistics, lastClose = d.prices[d.prices.length - 1];
  const ahead = st && st.volatility_percent !== null ? { price: lastClose[1], volatility: st.volatility_percent / 100 } : null;
  const until = ahead ? toDate(lastClose[0]).getTime() + YEAR_MS : null;
  const yearRange = ahead ? aheadRange(ahead, 0)[52] : null;
  return (
    <Card title={ahead ? "Share price, last 12 months and the year ahead" : "Share price, last 12 months"} wide
      hint={ma.length >= 2 ? null : `200-day average appears once 200 days of prices are stored (${d.prices.length} so far).`}>
      {ahead && yearRange ? <p className="range-says">{`In a typical year, ${c.asx_code} would end between `}<strong>{money(yearRange.lo)}</strong>
        {" and "}<strong>{money(yearRange.hi)}</strong>{" (two years in three). A guide to how much it moves, not a forecast."}</p> : null}
      <ChartSlot draw={(w) => lineChart({ series, yFmt: (v) => money(v), width: w, height: 260, markers, ahead,
        label: `${c.asx_code} closing price` + (ahead && yearRange ? `, and its likely range for the year ahead: ${money(yearRange.lo)} to ${money(yearRange.hi)}` : "") })} />
      {volumeChartFor(c, volumes, until)}
      {volumes.length >= 2 ? <p className="hint">Volume is the number of shares traded each day. A darker bar traded more than twice its 3-month average: news, results or a big holder buying or selling. <HelpLink id="volume" /></p> : null}
      <TableView headers={["Date", "Close", "Volume", "Dividend (ex-date)"]} rows={rowDates.map((dt) => [longDate(dt), money(closeOn.get(dt)),
        volOn.has(dt) ? fmt(volOn.get(dt), 0) : "", divOn.has(dt) ? dividendText(divOn.get(dt)!) : ""])} />
      {ahead && st ? <WorkedOut helpId="likely-range" paragraphs={[
        `The shaded range widens with time, because the further ahead you look the less certain it is. It comes from how much ${c.asx_code}'s price has moved over the past ${pastYears(st.years_of_prices)} (about ${fmt(st.volatility_percent, 0)}% a year), and assumes no trend: it doesn't know about results, dividends or news.`,
        "One year in six the price would end above the range, and one year in six below it."]} /> : null}
    </Card>
  );
}
const volumeChartFor = (c: Company, volumes: Point[], until: number | null) =>
  volumes.length >= 2 ? <ChartSlot draw={(w) => volumeChart({ points: volumes, label: `${c.asx_code} daily volume`, width: w, until })} /> : null;

function Financials({ d }: { d: CompanyData }) {
  const fy = d.reports.map((r) => `FY${String(r.fiscal_year).slice(-2)}`);
  const fin = d.reports.length ? (
    <Card title="Revenue and net profit" hint="Annual reports, oldest to newest.">
      <ChartSlot draw={(w) => columnChart({ categories: fy, yFmt: compact, label: "Revenue and net profit by year", width: w, series: [
        { name: "Revenue", color: "--s1", values: d.reports.map((r) => r.revenue) },
        { name: "Net profit after tax", color: "--s2", values: d.reports.map((r) => r.net_profit_after_tax) }] })} />
      <TableView headers={["Year", "Revenue", "Net profit", "Free cash flow"]} rows={d.reports.map((r, i) => [fy[i], compact(r.revenue), compact(r.net_profit_after_tax), compact(r.free_cash_flow)])} />
    </Card>
  ) : <Card title="Revenue and net profit" hint="No annual reports stored." />;
  const abnormal = d.reports.map((r, i) => [fy[i], r.abnormal_distributions_per_share] as [string, number | null]).filter(([, v]) => v !== null && v > 0);
  const abnormalNote = abnormal.length ? <p className="hint note">{`Excluded from every dividend figure: ${abnormal.map(([y, v]) => `${money(v, 3)} in ${y}`).join(", ")}. ` +
    "A one-off payment more than twice the usual annual dividend, such as a capital return or large special dividend."}</p> : null;
  const div = d.reports.some((r) => r.dividends_per_share) ? (
    <Card title="Dividends per share" hint="Ordinary cash dividends per financial year, before franking credits.">
      {abnormalNote}
      <ChartSlot draw={(w) => columnChart({ categories: fy, yFmt: (v) => money(v), label: "Dividends per share by year", width: w,
        series: [{ name: "Dividend per share", color: "--s1", values: d.reports.map((r) => r.dividends_per_share) }] })} />
      <TableView headers={["Year", "Dividend per share", "Excluded one-off"]} rows={d.reports.map((r, i) =>
        [fy[i], money(r.dividends_per_share, 3), r.abnormal_distributions_per_share ? money(r.abnormal_distributions_per_share, 3) : "none"])} />
    </Card>
  ) : <Card title="Dividends per share" hint="No dividends recorded.">{abnormalNote}</Card>;
  return <>{fin}{div}</>;
}

function CompanyBody({ d }: { d: CompanyData }) {
  const c = d.company;
  const [lists, setLists] = useState<WatchEntry[]>(d.watchlists);
  const scores = d.axes.map((a) => d.scores[a].score);
  const total = sum(scores);
  const mos = c.margin_of_safety_percent;
  const method = c.valuation_method === "DDM" ? "dividend discount model" : c.valuation_method === "DCF" ? "discounted cash flow model" : null;
  const ratios: [string, string][] = [["P/E", fmt(c.pe_ratio, 1)], ["P/B", fmt(c.pb_ratio, 2)], ["Price to free cash flow", fmt(c.price_to_fcf, 1)],
    ["EV/EBIT", fmt(c.ev_to_ebit, 1)], ["ROE", pct(c.roe)], ["ROIC", pct(c.roic)], ["Debt/equity", fmt(c.debt_to_equity, 2)],
    ["Cash dividend yield", pct(c.uncapped_dividend_yield)], ["Grossed-up yield", pct(c.grossed_up_dividend_yield)],
    ["Payout ratio", pct(c.payout_ratio, 0)], ["Country", c.country || NA], ["Accounts currency", accountsCurrency(c, d.reports)]];
  return (
    <>
      <BackLink />
      <div className="co-head">
        <h1>{c.company_name || c.asx_code}</h1>
        <span className="ticker mono">{c.asx_code}</span>
        <ValuationPill mos={mos} large />
        <Badge action={c.action} />
        <CautionTag level={d.short_caution && d.short_caution.level} />
        <WatchButton code={c.asx_code} lists={lists} onChange={setLists} />
      </div>
      <p className="co-sub">{[c.sector, c.industry, c.country].filter(Boolean).join("  |  ")}</p>
      <AboutCompany c={c} />
      <p className="reason">{c.action_reason}</p>
      {c.statements_issue ? <p className="hint note">{`The latest statements couldn't be stored: ${c.statements_issue.replace(/^statements can't be converted: /, "")}. ` +
        "Sift keeps the figures it had, sets data confidence to low (so this can't be a BUY) and tries again each night. Check the company's reports before relying on these numbers."}</p> : null}
      <SummaryStrip c={c} model={d.model} />
      <ModelNote model={d.model} />
      {d.position ? <p className="hint">{`You hold ${fmt(d.position.units, 0)} units, cost base ${money(d.position.cost_base)}.` +
        (d.position.next_discount_date ? ` ${fmt(d.position.units_pending_discount, 0)} units qualify for the CGT discount from ${longDate(d.position.next_discount_date)}.` : "")}</p> : null}
      <WatchNote lists={lists} />
      <div className="cards">
        <Card title="Score" hint={`${total} of ${d.checks_per_axis * d.axes.length} checks passed. Hover a spoke to see its checks.`}>
          <ChartSlot draw={(w) => wheel(scores, d.axes, d.checks_per_axis, { size: Math.min(300, w - 160), details: d.scores })} />
        </Card>
        <Card title="Price against estimated value" hint={method ? `Estimated value from a ${method}. Graham Number shown for reference.` : "No intrinsic value estimate could be made for this company."}>
          <ChartSlot draw={(w) => valuationBars([
            { label: "Share price", value: c.current_price, emphasis: true, help: host().fieldHelp("Share price") },
            { label: "Estimated value", value: c.dcf_intrinsic_value, help: host().estimatedValueHelp(c.valuation_method) },
            { label: "Graham Number", value: c.graham_number, help: host().fieldHelp("Graham Number") }], w)} />
          <ChancesBlock c={c} st={d.statistics} />
        </Card>
        <Card title="Four value tests" hint="The core screen. All four must pass for an overall pass.">
          <PassList items={d.tests.map((t) => ({ passed: t.passed, label: `${t.name}: ${t.value === null ? NA : fmt(t.value, t.unit === "%" ? 1 : 2) + t.unit} (needs ${t.rule})` }))} />
        </Card>
        <Breakdown d={d} />
        <Markers c={c} flags={d.flags} />
        <Card title="Key ratios"><KV rows={ratios} help /></Card>
        <PriceCard c={c} d={d} />
        {d.mos_history.length >= 2 ? (
          <Card title="Margin of safety over time" hint="The pink line is 0%, where the price equals estimated value. Above it: trading below estimated value.">
            <ChartSlot draw={(w) => lineChart({ series: [{ name: "Margin of safety", color: "--s1", points: d.mos_history }], yFmt: (v) => fmt(v, 0) + "%", zeroLine: true, label: "Margin of safety history", width: w })} />
            <TableView headers={["Date", "Margin of safety"]} rows={d.mos_history.slice(-30).reverse().map((p) => [longDate(p[0]), pct(p[1])])} />
          </Card>
        ) : <Card title="Margin of safety over time" hint="Builds up as the nightly job records a valuation each day." />}
        <Financials d={d} />
        <DrpCard x={d.drp} />
        <RegistryCard code={c.asx_code} info={d.registry} />
        <AnalystCard ins={c.insights} />
        <TargetCard ins={c.insights} c={c} />
        <HoldersCard ins={c.insights} />
        <FinancialHealthCard code={c.asx_code} health={d.health || null} />
        <ShortSellingCard c={c} d={d} />
        <NoticesCard list={c.notices} />
        <WorkingsCard code={c.asx_code} />
      </div>
    </>
  );
}

export function CompanyPage({ code }: { code: string }) {
  const [d, setD] = useState<CompanyData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    hideTip();
    const fund = host().fundHref(code);
    if (fund) { location.replace(fund); return; }
    let live = true;
    setD(null); setError(null);
    getJSON<CompanyData>(`/api/company/${encodeURIComponent(code)}`)
      .then((x) => { if (live) { setD(x); window.scrollTo(0, 0); } }, (e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [code]);
  if (error) return <><BackLink /><p className="error">{error}</p></>;
  if (!d) return <Loading text={`Loading ${code}...`} />;
  return <CompanyBody d={d} />;
}
