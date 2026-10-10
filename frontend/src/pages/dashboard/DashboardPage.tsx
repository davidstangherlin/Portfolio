// The dashboard: #/. Your portfolio's figures, then the widgets in your
// layout (DashLayout), then the nightly data's status.
import { useEffect, useState, type ReactElement } from "react";
import { Badge, ClickableRow, ErrorLine, Loading, PageHead } from "../../components/bits";
import { Card } from "../../components/Card";
import { DashLayout, type WidgetSpec } from "../../components/DashLayout";
import { HelpTh } from "../../components/FieldHelp";
import { MiniWheel } from "../../components/MiniWheel";
import { NoticeLine, type Notice } from "../../components/notices";
import { TrackingCard } from "../../components/track";
import { ValuationPill } from "../../components/common";
import { getJSON } from "../../lib/api";
import type { Layout } from "../../lib/dashLayout";
import { fmt, longDate, money, pct, plural, signClass, signed, sum } from "../../lib/format";
import { host, type Thresholds } from "../../lib/host";
import { statusLines, type Status } from "../../lib/status";
import type { TrackingStatus } from "../../lib/types";
import { FUNDS, fundHref, NameCell, PremCell, RetCell, RowTo, type FundRow, type Kind } from "../funds/common";
import { portfolioHref, type PortfolioSummary } from "../portfolio/common";
import { PortfolioStrip, SectionLine, type Sections, type Totals } from "../portfolio/holdings";

type N = number | null;
interface Trig { asx_code: string; triggers: { label: string }[]; watchlist_id: string; watchlist: string; note: string | null }
interface FundDash {
  count: number; triggered: Trig[]; cgt_soon: { asx_code: string; date: string; units: number; days: number }[];
  followed: (FundRow & { day_change_percent: N; premium_now: N; return_1y: N; distribution_yield_12m: N })[]; more: number;
  value: { holdings: number; value: N; day_change: N };
}
interface MoverRow extends FundRow { scores?: number[] | null; price: N; change_percent: N }
interface MoverGroup { as_of: string | null; traded: number; up: MoverRow[]; down: MoverRow[] }
interface Dashboard {
  status: Status; axes: string[]; checks_per_axis: number; companies: number; action_counts: Record<string, number>;
  attention: { asx_code: string; action: string; action_reason: string }[]; triggered: Trig[]; not_screened: string[];
  cgt_soon: { asx_code: string; date: string; units: number; days: number }[]; cgt_soon_days: number; etfs: FundDash | null; lics: FundDash | null;
  portfolio: Totals & { sections: Sections; portfolios: PortfolioSummary[] }; tracking: TrackingStatus;
  changes: { from_date: string | null; to_date: string; changes: { asx_code: string; company_name: string | null; direction: string; watchlists: string[]; held: boolean; margin_of_safety_percent: N; previous: string; action: string }[] };
  top: { asx_code: string; company_name: string | null; scores: number[]; margin_of_safety_percent: N; action: string }[];
  layout: Layout | null; notices: Notice[] | null; movers: { shares: MoverGroup | null; etfs: MoverGroup | null; lics: MoverGroup | null } | null; thresholds: Thresholds;
}
const money0 = (v: number) => money(v, 0);

const CompanyLink = ({ code }: { code: string }) => <a className="row-link" href={`#/company/${code}`}><span className="code">{code}</span></a>;

function AttentionCard({ d }: { d: Dashboard }) {
  const items = [
    ...d.attention.map((a) => <li key={`a${a.asx_code}`}><div className="main"><CompanyLink code={a.asx_code} /><Badge action={a.action} /><span className="detail">{a.action_reason}</span></div></li>),
    ...d.cgt_soon.map((c) => <li key={`c${c.asx_code}${c.date}`}><div className="main"><CompanyLink code={c.asx_code} /><span>{`CGT discount from ${longDate(c.date)}`}</span>
      <span className="detail">{`${fmt(c.units, 0)} units, ${plural(c.days, "day")} away. A sale before then gets no CGT discount on these units.`}</span></div></li>),
    d.not_screened.length ? <li key="ns"><div className="main"><span>{`Held but not screened: ${d.not_screened.join(", ")}`}</span>
      <span className="detail">Add them to the nightly ticker file (allords.txt) so they are valued each night.</span></div></li> : null,
    ...d.triggered.map((t) => <li key={`t${t.asx_code}${t.watchlist_id}`}><div className="main"><CompanyLink code={t.asx_code} /><span className="watch-star" aria-hidden="true">★</span>
      <span>{t.triggers.map((x) => x.label).join("; ")}</span>
      <span className="detail">Watchlist trigger met on <a href={`#/watchlist/${t.watchlist_id}`}>{t.watchlist}</a>{t.note ? `. Note: ${t.note}` : ""}</span></div></li>),
  ].filter(Boolean);
  return (
    <Card title="Needs attention" hint={items.length ? "Held shares flagged SELL or REVIEW, parcels reaching the CGT discount soon, and watchlist triggers met." : null}>
      {items.length ? <ul className="items">{items}</ul>
        : <p className="empty">{`Nothing needs attention: no held shares are flagged SELL or REVIEW, no parcel reaches the CGT discount in the next ${d.cgt_soon_days} days, and no watchlist trigger is met.`}</p>}
    </Card>
  );
}

const MAX_CHANGES = 12;
function ChangesCard({ d }: { d: Dashboard }) {
  const ch = d.changes;
  if (!ch.from_date) {
    const first = d.tracking.first_date;
    return <Card title="What changed"><p className="empty">{first
      ? `Appears after the second night of recording (first night ${longDate(first)}). Lists companies whose suggested action moved.`
      : "Appears once two nightly runs have recorded signals. Lists companies whose suggested action moved."}</p></Card>;
  }
  if (!ch.changes.length) return <Card title="What changed"><p className="empty">{`No suggested action changed between ${longDate(ch.from_date)} and ${longDate(ch.to_date)}.`}</p></Card>;
  const shown = ch.changes.slice(0, MAX_CHANGES);
  return (
    <Card title="What changed" hint={`${longDate(ch.from_date)} to ${longDate(ch.to_date)}: suggested actions that moved, watchlist companies (★) first, then better moves first.`}>
      <ul className="items">{shown.map((c) => (
        <li key={c.asx_code}>
          <span className={`move ${c.direction}`} aria-label={c.direction === "up" ? "Better" : "Worse"}>{c.direction === "up" ? "▲" : "▼"}</span>
          <div className="main"><CompanyLink code={c.asx_code} />
            {c.watchlists && c.watchlists.length ? <span className="watch-star" title={`On watchlist: ${c.watchlists.join(", ")}`} aria-label={`On watchlist ${c.watchlists.join(", ")}`}>★</span> : null}
            {c.held ? <span className="held-tag">HELD</span> : null}
            <span className="detail">{`${c.company_name || ""}${c.margin_of_safety_percent !== null ? `, margin of safety ${pct(c.margin_of_safety_percent, 0)}` : ""}`}</span></div>
          <div className="side"><Badge action={c.previous} /><span className="arrow" aria-label="to">→</span><Badge action={c.action} /></div>
        </li>
      ))}</ul>
      {ch.changes.length > MAX_CHANGES ? <p className="card-foot">{`and ${ch.changes.length - MAX_CHANGES} more.`}</p> : null}
    </Card>
  );
}

function TopCard({ d }: { d: Dashboard }) {
  const counts = d.action_counts;
  const parts = ["BUY", "INVESTIGATE"].filter((a) => counts[a]).map((a) => `${counts[a]} ${a}`);
  return (
    <Card title="Top opportunities" wide hint="Shares you don't hold: BUY first, then INVESTIGATE, highest score first.">
      {d.top.length ? (
        <div className="table-wrap"><table className="grid compact">
          <thead><tr>{["Score", "Company", "Margin of safety", "Valuation", "Action"].map((x, i) =>
            <HelpTh key={x} label={x} tab className={[i === 2 ? "center" : "", i === 0 || i === 3 ? "opt2" : ""].join(" ").trim() || undefined} />)}</tr></thead>
          <tbody>{d.top.map((r) => (
            <ClickableRow key={r.asx_code} code={r.asx_code}>
              <td className="opt2"><MiniWheel scores={r.scores} axes={d.axes} max={d.checks_per_axis} /><span className="score-total">{sum(r.scores)}</span></td>
              <td><span className="code">{r.asx_code}</span><div className="name">{r.company_name || ""}</div></td>
              <td className={`center tabular ${signClass(r.margin_of_safety_percent) || ""}`.trim()}>{pct(r.margin_of_safety_percent, 0)}</td>
              <td className="opt2"><ValuationPill mos={r.margin_of_safety_percent} /></td>
              <td><Badge action={r.action} /></td>
            </ClickableRow>
          ))}</tbody>
        </table></div>
      ) : <p className="empty">No BUY or INVESTIGATE signals today.</p>}
      {parts.length ? <p className="card-foot"><a href="#/screener?action=BUY,INVESTIGATE">{`See all ${parts.join(" and ")} in the screener →`}</a></p> : null}
    </Card>
  );
}

/* Biggest movers on the last trading day, by percentage: 5 each way for
   screener shares (with their score wheel), ETFs and LICs. */
function MoversCard({ m, d }: { m: NonNullable<Dashboard["movers"]>; d: Dashboard }) {
  const groups = ([["Shares in the screener", m.shares, (c: string) => `#/company/${c}`, "SHARE"],
    ["ETFs", m.etfs, (c: string) => fundHref("ETF", c), "ETF"], ["LICs", m.lics, (c: string) => fundHref("LIC", c), "LIC"]] as [string, MoverGroup | null, (c: string) => string, string][])
    .filter(([, x]) => x && x.as_of) as [string, MoverGroup, (c: string) => string, string][];
  if (!groups.length) return <Card title="Biggest movers"><p className="empty">Appears once Sift has two closing prices to compare.</p></Card>;
  const day = groups[0][1].as_of as string;
  const price = (v: N) => money(v, v !== null && v !== undefined && v < 1 ? 3 : 2);
  const side = (title: string, rows: MoverRow[], href: (c: string) => string, kind: string, none: string) => {
    const share = kind === "SHARE";
    return (
      <div className="table-wrap"><table className="grid compact movers">
        <thead><tr>{share ? <HelpTh label="Score" tab /> : null}<th>{title}</th><th className="num opt2">Close</th><th className="num">Day move</th></tr></thead>
        <tbody>{rows.length ? rows.map((r) => (
          <RowTo key={r.asx_code} href={href(r.asx_code)}>
            {share ? <td className="mover-score">{r.scores ? <><MiniWheel scores={r.scores} axes={d.axes} max={d.checks_per_axis} /><span className="score-total">{sum(r.scores)}</span></> : null}</td> : null}
            <NameCell r={r} kind={kind as Kind} />
            <td className="num opt2 tabular">{price(r.price)}</td>
            <RetCell v={r.change_percent} cls="tabular" />
          </RowTo>
        )) : <tr><td colSpan={share ? 4 : 3} className="hint">{none}</td></tr>}</tbody>
      </table></div>
    );
  };
  return (
    <Card title="Biggest movers" wide hint={`Percentage change from the previous close to the close on ${longDate(day)}. ★ watchlist, HELD in a portfolio.`}>
      {groups.map(([label, x, href, kind]) => (
        <div key={label} className="movers-group">
          <h3 className="sub-head">{label}<span className="hint">{` · ranked from ${fmt(x.traded, 0)}${x.as_of !== day ? `, to ${longDate(x.as_of as string)}` : ""}`}</span></h3>
          <div className="movers-cols">{side("Biggest rises", x.up, href, kind, "Nothing rose.")}{side("Biggest falls", x.down, href, kind, "Nothing fell.")}</div>
        </div>
      ))}
    </Card>
  );
}

function FundDashCard({ kind, x }: { kind: Kind; x: FundDash | null }) {
  const F = FUNDS[kind];
  if (!x || !x.count) return <Card title={F.nouns}><p className="empty">{`No ${F.nouns} loaded yet. They arrive with the ASX's monthly report. `}<a href="#/help/asx-etf-report">How</a>.</p></Card>;
  const items = [
    ...x.triggered.map((t) => <li key={`t${t.asx_code}${t.watchlist_id}`}><div className="main">
      <a className="row-link" href={fundHref(kind, t.asx_code)}><span className="code">{t.asx_code}</span></a>
      <span className="watch-star" aria-hidden="true">★</span><span>{t.triggers.map((y) => y.label).join("; ")}</span>
      <span className="detail">Watchlist trigger met on <a href={`#/watchlist/${t.watchlist_id}`}>{t.watchlist}</a>{t.note ? `. Note: ${t.note}` : ""}</span></div></li>),
    ...x.cgt_soon.map((c) => <li key={`c${c.asx_code}${c.date}`}><div className="main">
      <a className="row-link" href={fundHref(kind, c.asx_code)}><span className="code">{c.asx_code}</span></a>
      <span>{`CGT discount from ${longDate(c.date)}`}</span><span className="detail">{`${fmt(c.units, 0)} ${kind === "LIC" ? "shares" : "units"}, ${plural(c.days, "day")} away.`}</span></div></li>),
  ];
  const heads = kind === "LIC" ? ["LIC", "Day move", "Premium/discount to NTA", "1-year return"] : ["ETF", "Day move", "1-year return", "Yield (12 months)"];
  const v = x.value;
  return (
    <Card title={F.nouns} wide hint={v.holdings ? `Your ${F.nouns}: ${money(v.value, 0)}, ${signed(v.day_change, money0)} today.` : `${plural(x.count, F.noun)} followed. Hold or watch some to see them here.`}>
      {items.length ? <ul className="items">{items}</ul> : null}
      {x.followed.length ? (
        <div className="table-wrap"><table className="grid compact">
          <thead><tr>{heads.map((t, i) => <HelpTh key={t} label={t} tab className={[i ? "num" : "", i === 3 ? "opt2" : ""].join(" ").trim() || undefined} />)}</tr></thead>
          <tbody>{x.followed.map((r) => (
            <RowTo key={r.asx_code} href={fundHref(kind, r.asx_code)}>
              <NameCell r={{ ...r, held: r.held ? true : null }} kind={kind} />
              <RetCell v={r.day_change_percent} />
              {kind === "LIC" ? <PremCell v={r.premium_now} /> : <RetCell v={r.return_1y} />}
              {kind === "LIC" ? <RetCell v={r.return_1y} cls="opt2" /> : <td className="num opt2">{pct(r.distribution_yield_12m, 1)}</td>}
            </RowTo>
          ))}</tbody>
        </table></div>
      ) : v.holdings ? null : <p className="empty">{`Add ${F.nouns} to a watchlist, or record a buy in a portfolio, and they appear here.`}</p>}
      {x.more ? <p className="card-foot">{`and ${x.more} more.`}</p> : null}
      <p className="card-foot"><a href={F.list}>{`${F.noun} screener →`}</a></p>
    </Card>
  );
}

/* One line per active portfolio, when there's more than one. */
function PortfoliosCard({ list }: { list: PortfolioSummary[] }) {
  return (
    <Card title="Portfolios">
      <ul className="items">{list.map((p) => (
        <li key={p.portfolio_id}>
          <div className="main"><a className="row-link" href={portfolioHref(p)}><span className="code">{p.name}</span></a><span className="detail">{`${p.tax_type_label}, ${plural(p.holdings, "holding")}`}</span></div>
          {p.holdings ? <div className="side"><div className="strong">{money(p.value, 0)}</div><div className={`detail ${signClass(p.gain) || ""}`.trim()}>{`${signed(p.gain, money0)} gain`}</div></div>
            : <div className="side detail">no holdings yet</div>}
        </li>
      ))}</ul>
      <p className="card-foot"><a href="#/portfolios">All portfolios →</a></p>
    </Card>
  );
}

function ActionsCard({ d }: { d: Dashboard }) {
  return (
    <Card title="Today's suggested actions" hint={`Across ${plural(d.companies, "screened company", "screened companies")}. Pick one to open the screener filtered to it.`}>
      <div className="action-chips">{Object.entries(d.action_counts).filter(([, n]) => n).map(([a, n]) =>
        <a key={a} className="chip" href={`#/screener?action=${a}`}><Badge action={a} /><span className="n">{n}</span></a>)}</div>
    </Card>
  );
}

function NoticesDashCard({ list }: { list: Notice[] }) {
  return (
    <Card title="Director and holder notices" hint="On the companies you hold or watch, from ASX in the last week.">
      {list.length ? <ul className="items notice-list">{list.slice(0, 8).map((n, i) => <NoticeLine key={i} n={n} />)}</ul> : <p className="hint">None on your companies this week.</p>}
      <div className="more-links"><a className="more-link" href="#/coattail?tab=directors">All director trades</a><a className="more-link" href="#/coattail?tab=substantial">All substantial holders</a></div>
    </Card>
  );
}

export function DashboardPage() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    let live = true;
    getJSON<Dashboard>("/api/dashboard").then((x) => {
      if (!live) return;
      host().setThresholds(x.thresholds);
      host().setStatus(x.status);
      setD(x); window.scrollTo(0, 0);
    }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, []);
  if (error) return <ErrorLine error={error} />;
  if (!d) return <Loading text="Loading dashboard..." />;
  const today = new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const pf = d.portfolio;
  // Full width unless you choose otherwise: the cards that are drawn wide when they have something to show.
  const movers = d.movers ? [d.movers.shares, d.movers.etfs, d.movers.lics].some((x) => x && x.as_of) : false;
  const wide: Record<string, boolean> = { movers, top: true, etfs: Boolean(d.etfs && d.etfs.count), lics: Boolean(d.lics && d.lics.count) };
  const spec = (id: string, title: string, card: ReactElement | null): WidgetSpec => ({ id, title, card, defaultWide: Boolean(wide[id]) });
  const specs = [
    spec("attention", "Needs attention", <AttentionCard d={d} />),
    spec("changes", "What changed", <ChangesCard d={d} />),
    spec("movers", "Biggest movers", d.movers ? <MoversCard m={d.movers} d={d} /> : null),
    spec("top", "Top opportunities", <TopCard d={d} />),
    spec("etfs", "ETFs", <FundDashCard kind="ETF" x={d.etfs} />),
    spec("lics", "LICs", <FundDashCard kind="LIC" x={d.lics} />),
    spec("portfolios", "Portfolios", pf.portfolios.length > 1 ? <PortfoliosCard list={pf.portfolios} /> : null),
    spec("actions", "Today's suggested actions", <ActionsCard d={d} />),
    spec("tracking", "Track record", <TrackingCard t={d.tracking} />),
    spec("notices", "Director and holder notices", <NoticesDashCard list={d.notices || []} />),
  ];
  return (
    <>
      <PageHead title="Dashboard" sub={today} />
      {pf.holdings.length ? <PortfolioStrip pf={pf} /> : null}
      {pf.holdings.length ? <SectionLine sections={pf.sections} /> : null}
      <DashLayout specs={specs} saved={d.layout} onSaved={(layout) => { d.layout = layout; }} />
      <div className="dash-foot">{statusLines(d.status).map((l) => <span key={l}>{l}</span>)}</div>
    </>
  );
}
