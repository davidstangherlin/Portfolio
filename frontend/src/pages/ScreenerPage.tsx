// ASX Stocks: the screener. #/screener, or ?action=BUY,INVESTIGATE, ?held=1
// or ?watchlist=NAME to open it with just that filter (a plain #/screener
// keeps whatever was set last).
import { useEffect, useReducer, useState } from "react";
import { Badge, ErrorLine, Loading, PageHead } from "../components/bits";
import { CautionTag, ValuationPill, valuationStatus } from "../components/common";
import { MiniWheel } from "../components/MiniWheel";
import { SortTh, sortRows, type Sort } from "../components/SortTh";
import { useTableFilter } from "../components/TableFilter";
import { WatchCell, WatchHead, type PageList } from "../components/watch";
import { getJSON } from "../lib/api";
import { cached, keep } from "../lib/cache";
import { fmt, longDate, money, NA, pct, signClass, sum } from "../lib/format";
import { host, type Thresholds } from "../lib/host";
import { forgetFilters, type Fields } from "../lib/tableFilter";

interface Row {
  asx_code: string; company_name: string | null; sector: string | null; current_price: number | null; margin_of_safety_percent: number | null;
  roe: number | null; debt_to_equity: number | null; grossed_up_dividend_yield: number | null; short_percent: number | null; short_caution: string | null;
  mos_ok: string; roe_ok: string; de_ok: string; yield_ok: string; overall: string; action: string; held: unknown; watchlists: string[]; scores: number[];
}
interface Screener { rows: Row[]; actions: string[]; sectors: string[]; axes: string[]; checks_per_axis: number; watchlists: PageList[]; thresholds: Thresholds; as_of: string | null }

const TESTS: [keyof Row, string][] = [["mos_ok", "Margin of safety"], ["roe_ok", "ROE"], ["de_ok", "Debt/equity"], ["yield_ok", "Yield"]];
const passes = (r: Row) => TESTS.filter(([k]) => r[k] === "Y").length;

interface Col { key: string; label: string; num?: boolean; opt?: boolean; opt3?: boolean; opt4?: boolean; narrowHide?: boolean; value: (r: Row, d: Screener) => unknown }
const COLUMNS: Col[] = [
  { key: "score", label: "Score", value: (r) => sum(r.scores) },
  { key: "asx_code", label: "Company", value: (r) => r.asx_code },
  { key: "sector", label: "Sector", opt: true, opt3: true, value: (r) => r.sector },
  { key: "current_price", label: "Price", num: true, narrowHide: true, value: (r) => r.current_price },
  { key: "margin_of_safety_percent", label: "Margin of safety", num: true, value: (r) => r.margin_of_safety_percent },
  { key: "valuation", label: "Valuation", narrowHide: true, opt4: true, value: (r) => r.margin_of_safety_percent },
  { key: "roe", label: "ROE", num: true, opt: true, value: (r) => r.roe },
  { key: "debt_to_equity", label: "Debt/equity", num: true, opt: true, value: (r) => r.debt_to_equity },
  { key: "grossed_up_dividend_yield", label: "Yield (grossed up)", num: true, opt: true, value: (r) => r.grossed_up_dividend_yield },
  { key: "short_percent", label: "% short", num: true, opt: true, value: (r) => r.short_percent },
  { key: "tests", label: "Value tests", opt: true, opt4: true, value: (r) => passes(r) },
  { key: "action", label: "Action", value: (r, d) => d.actions.indexOf(r.action) },
];
const colClass = (c: Col) => [c.num ? "num" : "", c.opt ? "opt" : "", c.opt3 ? "opt3" : "", c.opt4 ? "opt4" : "", c.narrowHide ? "opt2" : ""].join(" ").trim() || undefined;

/* Each column as a filter field: its value, and its text as shown. */
const FIELDS: Fields<Row> = {
  score: { label: "Score", type: "num", get: (r) => sum(r.scores) },
  asx_code: { label: "Company", type: "text", get: (r) => r.asx_code, text: (r) => `${r.asx_code} ${r.company_name || ""}` },
  sector: { label: "Sector", type: "text", get: (r) => r.sector },
  current_price: { label: "Price", type: "num", get: (r) => r.current_price, text: (r) => money(r.current_price) },
  margin_of_safety_percent: { label: "Margin of safety", type: "num", get: (r) => r.margin_of_safety_percent, text: (r) => pct(r.margin_of_safety_percent, 0) },
  valuation: { label: "Valuation", type: "text", get: (r) => valuationStatus(r.margin_of_safety_percent).label },
  roe: { label: "ROE", type: "num", get: (r) => r.roe, text: (r) => pct(r.roe, 1) },
  debt_to_equity: { label: "Debt/equity", type: "num", get: (r) => r.debt_to_equity, text: (r) => fmt(r.debt_to_equity, 2) },
  grossed_up_dividend_yield: { label: "Yield (grossed up)", type: "num", get: (r) => r.grossed_up_dividend_yield, text: (r) => pct(r.grossed_up_dividend_yield, 1) },
  short_percent: { label: "% short", type: "num", get: (r) => r.short_percent, text: (r) => pct(r.short_percent, 1) },
  tests: { label: "Value tests", type: "num", get: (r) => passes(r) },
  action: { label: "Action", type: "text", get: (r) => r.action },
};

const pageSize = () => host().settings().rows_shown;
const state = { sector: "", actions: new Set<string>(), passing: false, held: false, watchlist: "", sort: { key: "action", dir: "asc" } as Sort, shown: 0 };

function preset(query: string | undefined) {
  if (query === undefined) return;
  const params = new URLSearchParams(query);
  Object.assign(state, { sector: "", passing: false, held: params.get("held") === "1", shown: pageSize(),
    watchlist: params.get("watchlist") || "", actions: new Set((params.get("action") || "").split(",").filter(Boolean)) });
  forgetFilters("screener");  // and none of the table filters, so the link shows what it says
}

function YnMarks({ r }: { r: Row }) {
  return <span className="tests">{TESTS.map(([k, label]) => {
    const pass = r[k] === "Y";
    return <span key={k} className={`yn ${pass ? "y" : "n"}`} title={`${label}: ${pass ? "pass" : "fail"}`} aria-label={`${label} ${pass ? "passes" : "fails"}`}>{pass ? "✓" : "✕"}</span>;
  })}</span>;
}

function ScreenerTable({ d }: { d: Screener }) {
  const [, bump] = useReducer((x: number) => x + 1, 0);
  if (!state.shown) state.shown = pageSize();
  const reset = () => { state.shown = pageSize(); bump(); };
  const tf = useTableFilter("screener", FIELDS, d.rows, reset, { placeholder: "Search any column" });
  if (state.watchlist && state.watchlist !== "*" && !d.watchlists.some((w) => w.name === state.watchlist)) state.watchlist = "";
  const filtered = d.rows.filter((r) =>
    (!state.sector || r.sector === state.sector) &&
    (state.actions.size === 0 || state.actions.has(r.action)) &&
    (!state.passing || r.overall === "Y") &&
    (!state.held || r.held !== null) &&
    (!state.watchlist || (state.watchlist === "*" ? r.watchlists.length > 0 : r.watchlists.includes(state.watchlist))));
  const col = COLUMNS.find((c) => c.key === state.sort.key) as Col;
  const rows = sortRows(tf.apply(filtered), (r) => col.value(r, d), state.sort.dir, (r) => r.margin_of_safety_percent ?? -Infinity);
  const shown = rows.slice(0, state.shown);
  const sortBy = (c: Col) => {
    state.sort = state.sort.key === c.key ? { key: c.key, dir: state.sort.dir === "asc" ? "desc" : "asc" }
      : { key: c.key, dir: c.key === "action" || c.key === "asx_code" || c.key === "sector" ? "asc" : "desc" };
    bump();
  };
  const open = (code: string) => { location.hash = `#/company/${code}`; };
  return (
    <>
      <PageHead title="ASX Stocks" sub={`Screener: ${d.rows.length} companies${d.as_of ? ", valuations as at " + longDate(d.as_of) : ""}`} />
      <div className="chips" role="group" aria-label="Filter by action">
        {d.actions.map((action) => {
          const n = d.rows.filter((r) => r.action === action).length;
          return n ? (
            <button key={action} className="chip" type="button" data-action={action} aria-pressed={state.actions.has(action)}
              onClick={() => { if (state.actions.has(action)) state.actions.delete(action); else state.actions.add(action); reset(); }}>
              <Badge action={action} /><span className="n">{n}</span>
            </button>
          ) : null;
        })}
      </div>
      <div className="controls">
        {tf.search}{tf.toggle}
        <select aria-label="Sector" value={state.sector} onChange={(e) => { state.sector = e.target.value; reset(); }}>
          <option value="">All sectors</option>{d.sectors.map((sc) => <option key={sc} value={sc}>{sc}</option>)}
        </select>
        {d.watchlists.length ? (
          <select aria-label="Watchlist" value={state.watchlist} onChange={(e) => { state.watchlist = e.target.value; reset(); }}>
            <option value="">All companies</option><option value="*">On any watchlist</option>
            {d.watchlists.map((w) => <option key={w.watchlist_id} value={w.name}>{`Watchlist: ${w.name}`}</option>)}
          </select>
        ) : null}
        <label><input type="checkbox" checked={state.passing} onChange={(e) => { state.passing = e.target.checked; reset(); }} />Passes all four tests</label>
        <label><input type="checkbox" checked={state.held} onChange={(e) => { state.held = e.target.checked; reset(); }} />Held only</label>
        <span className="count">{`${rows.length} shown`}</span>
      </div>
      {tf.chips}{tf.builder}
      <div className="table-wrap">
        <table className="grid" {...tf.tableProps([null, ...COLUMNS.map((c) => c.key)], () => shown)}>
          <thead><tr><WatchHead />{COLUMNS.map((c) => <SortTh key={c.key} label={c.label} sortKey={c.key} sort={state.sort} onSort={() => sortBy(c)} className={colClass(c)} />)}</tr></thead>
          <tbody>{shown.map((r) => (
            <tr key={r.asx_code} tabIndex={0} onClick={() => open(r.asx_code)} onKeyDown={(e) => { if (e.key === "Enter") open(r.asx_code); }}>
              <WatchCell r={r} lists={d.watchlists} onChange={bump} />
              <td><MiniWheel scores={r.scores} axes={d.axes} max={d.checks_per_axis} /><span className="score-total">{sum(r.scores)}</span></td>
              <td><span className="code">{r.asx_code}</span>{r.held !== null ? <span className="held-tag">HELD</span> : null}<div className="name">{r.company_name || ""}</div></td>
              <td className="opt opt3">{r.sector || NA}</td>
              <td className="num opt2">{money(r.current_price)}</td>
              <td className={`num ${signClass(r.margin_of_safety_percent) || ""}`.trim()}>{pct(r.margin_of_safety_percent, 0)}</td>
              <td className="opt2 opt4"><ValuationPill mos={r.margin_of_safety_percent} /></td>
              <td className="num opt">{pct(r.roe, 1)}</td>
              <td className="num opt">{fmt(r.debt_to_equity, 2)}</td>
              <td className="num opt">{pct(r.grossed_up_dividend_yield, 1)}</td>
              <td className={`num opt${r.short_caution ? " caution-text" : ""}`}>{r.short_percent === null || r.short_percent === undefined ? "" : pct(r.short_percent, 1)}</td>
              <td className="opt opt4"><YnMarks r={r} /></td>
              <td><Badge action={r.action} /><CautionTag level={r.short_caution} iconOnly /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <button className="more" type="button" hidden={rows.length <= state.shown || undefined} onClick={() => { state.shown += pageSize(); bump(); }}>
        {`Show more (${rows.length - state.shown} remaining)`}</button>
    </>
  );
}

export function ScreenerPage({ query }: { query?: string }) {
  const [d, setD] = useState<Screener | null>(() => cached<Screener>("screener") ?? null);
  const [error, setError] = useState<Error | null>(null);
  const [ready] = useState(() => { preset(query); return true; });
  useEffect(() => {
    if (d) { host().setThresholds(d.thresholds); return; }
    let live = true;
    getJSON<Screener>("/api/screener").then((x) => { if (live) { host().setThresholds(x.thresholds); setD(keep("screener", x)); } }, (e: Error) => live && setError(e));
    return () => { live = false; };
  }, [d]);
  if (error) return <ErrorLine error={error} />;
  if (!d || !ready) return <Loading text="Loading companies..." />;
  return <ScreenerTable d={d} />;
}
