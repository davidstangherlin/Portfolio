// The ETF and LIC lists: #/etfs and #/lics, or ?category=, ?held=1,
// ?watchlist= to open with just that filter.
import { useEffect, useReducer, useState, type ReactNode } from "react";
import { ErrorLine, Loading, PageHead } from "../../components/bits";
import { HelpLink } from "../../components/HelpLink";
import { SortTh, sortRows, type Sort } from "../../components/SortTh";
import { useTableFilter } from "../../components/TableFilter";
import { WatchCell, WatchHead, type PageList } from "../../components/watch";
import { getJSON } from "../../lib/api";
import { fmt, longDate, money, NA, pct, plural, signedPct } from "../../lib/format";
import { host } from "../../lib/host";
import { forgetFilters, type Field, type Fields } from "../../lib/tableFilter";
import { FUNDS, fundHref, fundSize, monthName, NameCell, premText, PremCell, RetCell, RowTo, type FundRow, type Kind } from "./common";

interface Col { key: string; label: string; short?: string; num?: boolean; cls?: string; cell: (r: FundRow) => ReactNode }
const n = (r: FundRow, k: string) => r[k] as number | null;
const COLUMNS: Record<Kind, Col[]> = {
  ETF: [
    { key: "asx_code", label: "ETF", cell: (r) => <NameCell r={r} kind="ETF" star={false} /> },
    { key: "category", label: "Category", cls: "opt3", cell: (r) => <td className="opt3"><div className="clip" title={r.category}>{r.category}</div></td> },
    { key: "issuer", label: "Issuer", cls: "opt4", cell: (r) => <td className="opt4"><div className="clip" title={r.issuer || ""}>{r.issuer || NA}</div></td> },
    { key: "mer_percent", label: "Fee", num: true, cell: (r) => <td className="num">{pct(n(r, "mer_percent"), 2)}</td> },
    { key: "fum_aud", label: "Fund size", num: true, cls: "opt2", cell: (r) => <td className="num opt2">{fundSize(n(r, "fum_aud"))}</td> },
    { key: "return_1y", label: "1-year return", short: "1 yr", num: true, cell: (r) => <RetCell v={n(r, "return_1y")} /> },
    { key: "return_3y", label: "3-year return", num: true, cls: "opt3", cell: (r) => <RetCell v={n(r, "return_3y")} cls="opt3" /> },
    { key: "return_5y", label: "5-year return", num: true, cls: "opt2", cell: (r) => <RetCell v={n(r, "return_5y")} cls="opt2" /> },
    { key: "return_10y", label: "10-year return", num: true, cls: "opt3", cell: (r) => <RetCell v={n(r, "return_10y")} cls="opt3" /> },
    { key: "distribution_yield_12m", label: "Yield (12 months)", short: "Yield", num: true, cell: (r) => <td className="num">{pct(n(r, "distribution_yield_12m"), 1)}</td> },
    { key: "avg_spread_percent", label: "Spread", num: true, cls: "opt", cell: (r) => <td className="num opt">{pct(n(r, "avg_spread_percent"), 2)}</td> },
  ],
  LIC: [
    { key: "asx_code", label: "LIC", cell: (r) => <NameCell r={r} kind="LIC" star={false} /> },
    { key: "category", label: "Category", cls: "opt3", cell: (r) => <td className="opt3"><div className="clip" title={r.category}>{r.category}</div></td> },
    { key: "premium_now", label: "Premium/discount to NTA", short: "vs NTA", num: true, cell: (r) => <PremCell v={n(r, "premium_now")} /> },
    { key: "mer_percent", label: "Fee", num: true, cell: (r) => <td className="num">{pct(n(r, "mer_percent"), 2)}</td> },
    { key: "performance_fee", label: "Performance fee", cls: "opt", cell: (r) => <td className="opt">{(r.performance_fee as string) || NA}</td> },
    { key: "fum_aud", label: "Market cap", num: true, cls: "opt2", cell: (r) => <td className="num opt2">{fundSize(n(r, "fum_aud"))}</td> },
    { key: "return_1y", label: "1-year return", short: "1 yr", num: true, cell: (r) => <RetCell v={n(r, "return_1y")} /> },
    { key: "return_3y", label: "3-year return", num: true, cls: "opt3", cell: (r) => <RetCell v={n(r, "return_3y")} cls="opt3" /> },
    { key: "return_5y", label: "5-year return", num: true, cls: "opt2", cell: (r) => <RetCell v={n(r, "return_5y")} cls="opt2" /> },
    { key: "distribution_yield_12m", label: "Yield (12 months)", short: "Yield", num: true, cell: (r) => <td className="num">{pct(n(r, "distribution_yield_12m"), 1)}</td> },
  ],
};

/* Each column as a filter field, with its text as shown. */
const FUND_TEXT: Record<string, (v: number | null) => string> = { mer_percent: (v) => pct(v, 2), fum_aud: fundSize, distribution_yield_12m: (v) => pct(v, 1),
  avg_spread_percent: (v) => pct(v, 2), premium_now: premText, day_change_percent: (v) => signedPct(v), price: (v) => money(v) };
function fundField(key: string, label: string, num?: boolean): Field<FundRow> {
  const show = FUND_TEXT[key] || (key.startsWith("return_") ? (v: number | null) => signedPct(v) : (v: number | null) => fmt(v, 2));
  if (key === "asx_code") return { label, type: "text", get: (r) => r.asx_code, text: (r) => `${r.asx_code} ${r.company_name || ""}` };
  return num ? { label, type: "num", get: (r) => r[key], text: (r) => show(r[key] as number | null) } : { label, type: "text", get: (r) => r[key] };
}
const fieldsFor = (kind: Kind): Fields<FundRow> => Object.fromEntries(COLUMNS[kind].map((c) => [c.key, fundField(c.key, c.label, c.num)]));
const FIELDS: Record<Kind, Fields<FundRow>> = { ETF: fieldsFor("ETF"), LIC: fieldsFor("LIC") };
const ASC = ["asx_code", "category", "issuer", "mer_percent", "avg_spread_percent", "premium_now", "performance_fee"];

const pageSize = () => host().settings().rows_shown;
interface ListState { category: string; issuer: string; watchlist: string; held: boolean; sort: Sort; shown: number }
const STATE: Record<Kind, ListState> = {
  ETF: { category: "", issuer: "", watchlist: "", held: false, sort: { ...FUNDS.ETF.sort }, shown: 0 },
  LIC: { category: "", issuer: "", watchlist: "", held: false, sort: { ...FUNDS.LIC.sort }, shown: 0 },
};
function preset(kind: Kind, query: string | undefined) {
  if (query === undefined) return;
  const params = new URLSearchParams(query);
  Object.assign(STATE[kind], { issuer: "", shown: pageSize(), held: params.get("held") === "1",
    category: params.get("category") || "", watchlist: params.get("watchlist") || "" });
  forgetFilters(kind);
}

interface FundList { rows: FundRow[]; categories: string[]; issuers: string[]; watchlists: PageList[]; as_of: string | null; report_month: string | null }

function FundsTable({ kind, d }: { kind: Kind; d: FundList }) {
  const F = FUNDS[kind], st = STATE[kind], columns = COLUMNS[kind];
  const [, bump] = useReducer((x: number) => x + 1, 0);
  if (!st.shown) st.shown = pageSize();
  const reset = () => { st.shown = pageSize(); bump(); };
  const tf = useTableFilter(kind, FIELDS[kind], d.rows, reset,
    { placeholder: "Search any column", extraSearch: (r) => [r.benchmark, r.issuer].filter(Boolean).join(" ") });
  const filtered = d.rows.filter((r) =>
    (!st.category || r.category === st.category) && (!st.issuer || r.issuer === st.issuer) && (!st.held || r.held !== null) &&
    (!st.watchlist || (st.watchlist === "*" ? r.watchlists.length > 0 : r.watchlists.includes(st.watchlist))));
  const rows = sortRows(tf.apply(filtered), (r) => r[st.sort.key], st.sort.dir, (r) => (r.fum_aud as number | null) ?? -Infinity);
  const shown = rows.slice(0, st.shown);
  const sortBy = (c: Col) => {
    st.sort = st.sort.key === c.key ? { key: c.key, dir: st.sort.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: ASC.includes(c.key) ? "asc" : "desc" };
    bump();
  };
  const select = (label: string, key: "category" | "issuer" | "watchlist", options: [string, string][], all: string) => (
    <select aria-label={label} value={st[key]} onChange={(e) => { st[key] = e.target.value; reset(); }}>
      <option value="">{all}</option>{options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
  );
  const counts = (v: string) => d.rows.filter((r) => r.category === v).length;
  const sub = [plural(d.rows.length, F.noun), d.as_of ? `performance as at ${longDate(d.as_of)}` : null,
    d.report_month ? `${kind === "LIC" ? "NTA and facts" : "fund facts"} from the ASX report for ${monthName(d.report_month)}` : null].filter(Boolean).join(", ");
  return (
    <>
      <PageHead title={F.nouns} sub={sub} />
      <p className="hint page-note">{F.intro} <HelpLink id={F.help} /></p>
      <div className="controls">
        {tf.search}{tf.toggle}
        {select("Category", "category", d.categories.map((c) => [c, `${c} (${counts(c)})`]), "All categories")}
        {d.issuers.length ? select("Issuer", "issuer", d.issuers.map((i) => [i, i]), "All issuers") : null}
        {d.watchlists.length ? select("Watchlist", "watchlist", [["*", "On any watchlist"], ...d.watchlists.map((w) => [w.name, `Watchlist: ${w.name}`] as [string, string])], `All ${F.nouns}`) : null}
        <label><input type="checkbox" checked={st.held} onChange={(e) => { st.held = e.target.checked; reset(); }} />Held only</label>
        <span className="count">{`${rows.length} shown`}</span>
      </div>
      {tf.chips}{tf.builder}
      <div className="table-wrap">
        <table className="grid etf-table" {...tf.tableProps([null, ...columns.map((c) => c.key)], () => shown)}>
          <thead><tr><WatchHead />{columns.map((c) => (
            <SortTh key={c.key} label={c.label} sortKey={c.key} sort={st.sort} onSort={() => sortBy(c)} className={[c.num ? "num" : "", c.cls || ""].join(" ").trim() || undefined}>
              {c.short ? <><span className="long">{c.label}</span><span className="short">{c.short}</span></> : c.label}
            </SortTh>
          ))}</tr></thead>
          <tbody>{shown.map((r) => (
            <RowTo key={r.asx_code} href={fundHref(kind, r.asx_code)}>
              <WatchCell r={r} lists={d.watchlists} onChange={bump} />
              {columns.map((c) => <CellOf key={c.key} c={c} r={r} />)}
            </RowTo>
          ))}</tbody>
        </table>
      </div>
      <button className="more" type="button" hidden={rows.length <= st.shown || undefined} onClick={() => { st.shown += pageSize(); bump(); }}>
        {`Show more (${rows.length - st.shown} remaining)`}</button>
    </>
  );
}
const CellOf = ({ c, r }: { c: Col; r: FundRow }) => <>{c.cell(r)}</>;

export function FundsPage({ kind, query }: { kind: Kind; query?: string }) {
  const F = FUNDS[kind];
  const [d, setD] = useState<FundList | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [ready] = useState(() => { preset(kind, query); return true; });
  useEffect(() => {
    let live = true;
    getJSON<FundList>(`/api/${F.api}s`).then((x) => { if (live) { setD(x); window.scrollTo(0, 0); } }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, [F.api]);
  if (error) return <ErrorLine error={error} />;
  if (!d || !ready) return <Loading text={`Loading ${F.nouns}...`} />;
  if (!d.rows.length) {
    return (
      <>
        <PageHead title={F.nouns} />
        <p className="empty">{`No ${F.nouns} yet. They come from the ASX's monthly report: save it in the data\\asx_reports folder and run `}
          <code>python -m src.etf.run_etfs</code>{" (or wait for tonight's run). "}<a href="#/help/asx-etf-report">How the list is loaded</a>.</p>
      </>
    );
  }
  return <FundsTable kind={kind} d={d} />;
}
