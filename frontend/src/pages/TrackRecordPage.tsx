// Track record: is Sift right, what did I miss, what should I look at now.
// #/track-record, or ?version=N for one rules version (from Admin).
import { useEffect, useState, type ReactNode } from "react";
import { edgeDomain, ptsText } from "../charts/edgeBar";
import { Badge, ClickableRow, ErrorLine, Loading, PageHead, WatchStar } from "../components/bits";
import { Card } from "../components/Card";
import { HelpTh } from "../components/FieldHelp";
import { horizonText, TrackingCard, VerdictLine } from "../components/track";
import { WorkedOut } from "../components/WorkedOut";
import { getJSON } from "../lib/api";
import { fmt, longDate, money, NA, pct, plural, signClass, signed, signedPct, toDate } from "../lib/format";
import { host } from "../lib/host";
import type { Signal, TrackRecord } from "../lib/types";

let rememberedHorizon: number | null = null;   // kept between visits, as before

function OrderLine({ status }: { status: string }) {
  if (status === "too early") return <p className="hint">Order check: too early. It needs 30 monthly signals each of BUY, WATCH and AVOID.</p>;
  return <p className={`order ${status === "in order" ? "pos" : "neg"}`}>{status === "in order"
    ? "In order: BUY beat WATCH, and WATCH beat AVOID. The rules rank companies the right way round."
    : "Out of order: BUY, WATCH and AVOID don't line up best to worst. The rules need review."}</p>;
}

function VerdictCard({ d, months, setHorizon }: { d: TrackRecord; months: number; setHorizon: (m: number) => void }) {
  const v = d.verdict[months];
  const due = (d.status.results_due || []).find((r) => r.months === months);
  const domain = edgeDomain(v.actions);
  const admin = host().isAdmin();
  const empty = !due ? "Results start once signals have been recorded for a month."
    : toDate(due.date) > new Date() ? `First ${months}-month results due ${longDate(due.date)}.`
    : d.version ? `No ${months}-month results yet for ${d.version_label || "this rules version"}: its signals aren't ${horizonText(months)} old yet.`
    : `First ${months}-month results arrive with the next nightly run.`;
  return (
    <Card title="Is Sift accurate?" wide
      hint="Each company's first signal of each month, against the average total return (dividends included) of every company screened that night. Points are percentage points.">
      <div className="segmented periods" role="group" aria-label="Period">
        {d.horizons.map((m) => <button key={m} type="button" aria-pressed={m === months} onClick={() => setHorizon(m)}>{horizonText(m)}</button>)}
      </div>
      {v.actions.length ? (
        <>
          <ul className="verdict rules">{v.actions.map((a) => <VerdictLine key={a.action} a={a} months={months} domain={domain} />)}</ul>
          <OrderLine status={v.order.status} />
          <WorkedOut helpId="rule-reliability" paragraphs={[
            `Each call's total return is compared with the average screened share's over the same ${horizonText(months)}. The bar shows where the action's true edge most likely sits. If the whole bar is clear of the average, the difference is very unlikely to be luck.`,
            "Calls a month apart overlap when the period is longer than a month, so Sift widens the bar to allow for that: it claims less, not more.",
            "Sift tests every action at every period at once, and with that many tests a few would pass by luck alone. It corrects for this (the Benjamini-Hochberg method), which widens the bars and adjusts the luck odds, so no more than 1 in 20 of the results it calls real should be luck.",
            `An action needs ${fmt(v.actions[0].test.min_calls, 0)} calls before Sift judges it (a setting in Admin, Model and rules).`]}>
            {admin ? <p className="hint">{"Admin: " + v.actions.filter((a) => a.test.t !== null).map((a) =>
              `${a.action} t = ${fmt(a.test.t, 2)}, p = ${fmt(a.test.p_value, 3)}, adjusted ${a.test.q_value === null || a.test.q_value === undefined ? "n/a" : fmt(a.test.q_value, 3)}, ${fmt(100 * (a.test.level ?? 0.95), 1)}% ${ptsText(a.test.low as number)} to ${ptsText(a.test.high as number)}`).join("; ")}</p> : null}
          </WorkedOut>
        </>
      ) : <p className="empty">{empty}</p>}
    </Card>
  );
}

function MonthlyCard({ d, months }: { d: TrackRecord; months: number }) {
  const rows = d.monthly.filter((r) => r.horizon_months === months);
  const order = d.verdict[months].actions;
  const rank = (a: string) => order.findIndex((x) => x.action === a);
  const actions = [...new Set(rows.map((r) => r.action))].sort((a, b) => rank(a) - rank(b));
  const monthsList = [...new Set(rows.map((r) => r.month))];
  const cell = (m: string, a: string) => rows.find((r) => r.month === m && r.action === a);
  return (
    <Card title={`By month, ${horizonText(months)} later`} wide
      hint="Average points above (+) or below (-) the average screened share, with the number of signals. Kept for good, after the daily detail is deleted.">
      {rows.length ? (
        <div className="table-wrap"><table className="grid compact">
          <thead><tr><th>Signals given in</th>{actions.map((a) => <th key={a} className="num">{a}</th>)}</tr></thead>
          <tbody>{monthsList.map((m) => (
            <tr key={m} className="static">
              <td>{toDate(m).toLocaleDateString("en-AU", { month: "long", year: "numeric" })}</td>
              {actions.map((a) => { const r = cell(m, a); return <td key={a} className={`num ${r ? signClass(r.avg_excess) || "" : ""}`.trim()}>{r ? `${signed(r.avg_excess, (x) => fmt(x, 1))} (${r.signals})` : ""}</td>; })}
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="empty">Fills in month by month as results arrive.</p>}
    </Card>
  );
}

interface Col { label: string; num?: boolean; opt?: boolean; help?: boolean; cls?: (it: Signal) => string | undefined; value: (it: Signal) => ReactNode }
const classes = (...xs: (string | undefined | false)[]) => xs.filter(Boolean).join(" ") || undefined;

function SignalTable({ items, cols }: { items: Signal[]; cols: Col[] }) {
  return (
    <div className="table-wrap"><table className="grid compact">
      <thead><tr>{cols.map((col) => col.help
        ? <HelpTh key={col.label} label={col.label} className={classes(col.num && "num", col.opt && "opt")} />
        : <th key={col.label} className={classes(col.num && "num", col.opt && "opt")}>{col.label}</th>)}</tr></thead>
      <tbody>{items.map((it, i) => (
        <ClickableRow key={`${it.asx_code}-${i}`} code={it.asx_code}>
          {cols.map((col) => <td key={col.label} className={classes(col.num && "num", col.opt && "opt", col.cls?.(it))}>{col.value(it)}</td>)}
        </ClickableRow>
      ))}</tbody>
    </table></div>
  );
}

const num = (it: Signal, k: string) => it[k] as number | null | undefined;
const companyCell: Col = { label: "Company", value: (it) => <><span className="code">{it.asx_code}</span><WatchStar lists={it.watchlists} /><div className="name">{it.company_name || ""}</div></> };
const signalCol: Col = { label: "Signal", value: (it) => <Badge action={it.action} /> };

/* What Sift's estimated value, the analysts' target and the Graham Number
   stood at on the night of the call, each with its gap to that night's price
   on hover. Blank before they were recorded. */
function targetsThen(priceKey: string): Col[] {
  const cell = (key: string, extra?: (it: Signal) => string) => (it: Signal) => {
    const v = num(it, key), price = num(it, priceKey);
    if (v === null || v === undefined) return "";
    const gap = price ? `${signedPct((v / price - 1) * 100, 0)} on the price then (${money(price)})` : "";
    return <span title={[gap, extra ? extra(it) : ""].filter(Boolean).join("; ")}>{money(v)}</span>;
  };
  return [
    { label: "Value then", num: true, opt: true, help: true, value: cell("value_then") },
    { label: "Target then", num: true, opt: true, help: true, value: cell("target_then", (it) => (it.analysts_then ? `mean of ${plural(it.analysts_then as number, "analyst")}` : "")) },
    { label: "Graham then", num: true, opt: true, help: true, value: cell("graham_then") },
  ];
}

function ActionableCard({ d }: { d: TrackRecord }) {
  const a = d.actionable, p = d.proven, mos = d.rules.margin_of_safety;
  const hint = p.proven
    ? `Signals of the kind that has beaten the average at ${horizonText(p.horizon)}: ${p.actions.join(", ")}. Only those still more than ${fmt(mos, 0)}% below estimated value.`
    : `Nothing is proven yet (too few results), so this lists today's ${p.actions.join(", ")} signals on the rules' own terms, more than ${fmt(mos, 0)}% below estimated value.`;
  const cols: Col[] = [companyCell, signalCol,
    { label: "Since", opt: true, value: (it) => (it.since ? longDate(it.since as string) : NA) },
    { label: "Price then", num: true, opt: true, value: (it) => money(num(it, "price_then")) },
    ...targetsThen("price_then"),
    { label: "Price now", num: true, value: (it) => money(num(it, "price_now")) },
    { label: "Margin of safety", num: true, cls: (it) => signClass(num(it, "margin_of_safety_now")), value: (it) => pct(num(it, "margin_of_safety_now"), 0) }];
  const group = (title: string, items: Signal[], empty: string, extra: Col[] = []) => (
    <>
      <h3 className="sub-head">{`${title} (${items.length})`}</h3>
      {items.length ? <SignalTable items={items} cols={cols.concat(extra)} /> : <p className="empty">{empty}</p>}
    </>
  );
  return (
    <Card title="What should I look at now?" hint={hint} wide>
      {group("New this week", a.new, "No new signals this week.")}
      {group("Still open", a.open, "None open.")}
      {group("Moved on", a.moved_on, "Nothing has moved on in the last 90 days.", [{ label: "Why", value: (it) => it.why as string }])}
    </Card>
  );
}

function MissedCard({ d }: { d: TrackRecord }) {
  const due = (d.status.results_due || [])[0];
  const empty = due && toDate(due.date) > new Date() ? `Appears once the first results arrive (${longDate(due.date)}).` : "None so far.";
  const later: Col = { label: "Ahead of average", num: true, cls: (it) => signClass(num(it, "excess_return")),
    value: (it) => `${signed(num(it, "excess_return"), (x) => fmt(x, 1))} pts (${horizonText(it.horizon_months as number)})` };
  const date: Col = { label: "Date", value: (it) => longDate(it.snapshot_date as string) };
  const priceThen: Col = { label: "Price then", num: true, opt: true, value: (it) => money(num(it, "price")) };
  return (
    <Card title="What did I miss?" wide
      hint={`BUY and INVESTIGATE calls on shares you didn't hold and didn't buy within ${d.rules.purchase_window_days} days, that beat the average by more than ${fmt(d.rules.missed_excess, 0)} points. First call per company; ★ marks your watchlists.`}>
      {d.missed.length ? <SignalTable items={d.missed} cols={[companyCell, signalCol, date, priceThen, ...targetsThen("price"),
        { label: "Price now", num: true, opt: true, value: (it) => money(num(it, "price_now")) }, later,
        { label: "Still undervalued", value: (it) => (it.price_now === null ? NA : it.still_undervalued ? "Yes" : "No") }]} /> : <p className="empty">{empty}</p>}
      <h3 className="sub-head">{`Calls that saved money (${d.saved.length})`}</h3>
      {d.saved.length ? <SignalTable items={d.saved} cols={[companyCell, signalCol, date, priceThen, ...targetsThen("price"),
        { label: "Return", num: true, cls: (it) => signClass(num(it, "total_return")), value: (it) => signedPct(num(it, "total_return")) }, later]} />
        : <p className="empty">{`AVOID calls on shares you didn't hold, and SELL calls on shares you did, that trailed the average by more than ${fmt(d.rules.missed_excess, 0)} points. ${empty}`}</p>}
    </Card>
  );
}

export function TrackRecordPage({ version = "" }: { version?: string }) {
  const [d, setD] = useState<TrackRecord | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [horizon, setHorizonState] = useState<number | null>(rememberedHorizon);
  useEffect(() => {
    let live = true;
    getJSON<TrackRecord>(`/api/track-record${version ? `?version=${encodeURIComponent(version)}` : ""}`)
      .then((x) => { if (live) { setD(x); window.scrollTo(0, 0); } }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, [version]);
  if (error) return <ErrorLine error={error} />;
  if (!d) return <Loading text="Loading track record..." />;
  const withData = d.horizons.filter((m) => d.verdict[m].actions.length);
  const months = horizon && d.horizons.includes(horizon) ? horizon : withData.includes(3) ? 3 : withData[0] || 1;
  const setHorizon = (m: number) => { rememberedHorizon = m; setHorizonState(m); };
  return (
    <>
      <PageHead title="Track record" sub="Is Sift right?" />
      {d.version ? <p className="hint page-note">{`Showing ${d.version_label || "one rules version"} only. `}<a href="#/track-record">Show every version</a></p> : null}
      <div className="cards">
        <VerdictCard d={d} months={months} setHorizon={setHorizon} />
        <ActionableCard d={d} />
        <MissedCard d={d} />
        <MonthlyCard d={d} months={months} />
        <TrackingCard t={d.status} withLink={false} />
        <Card title="How Sift is judged">
          <div className="prose">
            <p>Each night Sift records what it said about every screened company. Those records are never edited, so later rule changes can't rewrite history.</p>
            <p>Each company's first signal of each month is scored after 1, 3, 6 and 12 months: its total return including dividends, minus the average for every company screened that night. A company that stops trading is scored at its last price. A BUY that beats the average was right; an AVOID that trails it was right.</p>
            <p>{`Confidence: too early under ${d.rules.too_early_below} signals, moderate up to ${d.rules.solid_above}, solid above that. The daily detail is kept for 14 months; the monthly results are kept for good.`}</p>
          </div>
        </Card>
      </div>
    </>
  );
}
