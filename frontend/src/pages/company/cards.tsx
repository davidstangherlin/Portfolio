// The company page's information cards: chances, short selling, DRP, share
// registry, ASX notices and the workings (web/app.js equivalents named).
import { useRef, useState, type FormEvent } from "react";
import { lineChart, pastYears } from "../../charts/lineChart";
import { Badge } from "../../components/bits";
import { Card } from "../../components/Card";
import { ChartSlot } from "../../components/ChartSlot";
import { CautionTag, StatTile, ValuationPill, WithHelpLink } from "../../components/common";
import { HelpLink } from "../../components/HelpLink";
import { NoticeLine, type Notice } from "../../components/notices";
import { WorkedOut } from "../../components/WorkedOut";
import { getJSON, send } from "../../lib/api";
import { showMessage } from "../../lib/forms";
import { compact, fmt, longDate, money, NA, pct, plural } from "../../lib/format";
import { host } from "../../lib/host";
import type { Company, CompanyData, Drp, RegistryInfo, Statistics } from "./types";

/* Ten dots, filled for the chance in 10 ("about 4 in 10"). */
function ChanceDots({ n }: { n: number }) {
  return <span className="chance-dots" role="img" aria-label={`${n} in 10`}>{Array.from({ length: 10 }, (_, i) => <span key={i} className={`cdot${i < n ? " on" : ""}`} />)}</span>;
}
const CHANCE_SCALE = ["Very unlikely: less than 1 in 10", "Unlikely: 1 to 2 in 10", "Possible: 3 to 4 in 10", "About even: 5 in 10",
  "Likely: 6 to 7 in 10", "Very likely: 8 or more in 10"];

/* The chance of reaching Sift's estimated value and the analysts' target
   within 12 months, under the price against estimated value bars. */
export function ChancesBlock({ c, st }: { c: Company; st: Statistics | null }) {
  if (!st || !st.chances.length) return null;
  const admin = host().isAdmin();
  return (
    <div className="chances-block">
      <p className="mini-head"><WithHelpLink text="Chance of reaching it within 12 months" id="chance-of-reaching" /></p>
      <div className="chances">{st.chances.map((x) => (
        <div className="chance" key={x.label}>
          <span className="label">{x.label}<small>{`${money(x.level)}, ${fmt(Math.abs(x.above_today_percent), 0)}% ${x.above_today_percent >= 0 ? "above" : "below"} today`}</small></span>
          {x.already_reached ? <span className="words">Already reached: today's price is at or above it.</span>
            : x.words ? <><ChanceDots n={x.words.in_ten} /><span className="words"><strong>{`${x.words.word}: `}</strong>{x.words.text}</span></>
            : <span className="words hint">Needs a year of prices.</span>}
        </div>
      ))}</div>
      <p className="hint">{`Based on how much ${c.asx_code}'s price has moved over the past ${pastYears(st.years_of_prices)}. It doesn't know about future news or results.`}</p>
      <WorkedOut helpId="chance-of-reaching" paragraphs={[
        `Sift measures how much the price usually moves in a year (for ${c.asx_code}, about ${fmt(st.volatility_percent, 0)}%) and works out how often a price moving like that touches the level at least once within 12 months, assuming no trend either way.`,
        "The same words mean the same chance everywhere in Sift:"]}>
        <ul className="scale-words">{CHANCE_SCALE.map((t) => <li key={t}>{t}</li>)}</ul>
        {admin ? <p className="hint">{"Admin: " + st.chances.filter((x) => x.chance !== null).map((x) => `${x.label} ${fmt((x.chance as number) * 100, 0)}%`).join("; ") +
          `; volatility ${fmt(st.volatility_percent, 1)}% a year from ${fmt(st.observations, 0)} daily returns; beta ${st.beta === null ? NA : fmt(st.beta, 2)}${st.market_code ? ` against ${st.market_code}` : ""}.`}</p> : null}
      </WorkedOut>
    </div>
  );
}

/* The short selling card, written for everyday investors: a plain verdict
   first, then where the share sits, why it might be shorted and what it
   means for you; the figures and chart wait under a twisty
   (src/screening/short_caution.py gives the verdict and the "why"). */
export function ShortSellingCard({ c, d }: { c: Company; d: CompanyData }) {
  const x = d.short_interest, caution = d.short_caution, read = d.short_read, lv = d.short_levels;
  if (!x) return <Card title="Short selling" hint="No ASIC short position report for this company yet: they load nightly, about four business days behind."><HelpLink id="short-selling" /></Card>;
  const held = Boolean(d.position && d.position.units > 0);
  const s = x.short_percent, days = c.days_to_cover, ch = x.change_points;
  const known = (v: number | null | undefined): v is number => v !== null && v !== undefined;
  const bands: [string, string, number, number][] = [["Normal", `under ${fmt(lv.watch, 0)}%`, 0, lv.watch], ["Watch", `${fmt(lv.watch, 0)} to ${fmt(lv.elevated, 0)}%`, lv.watch, lv.elevated],
    ["Elevated", `${fmt(lv.elevated, 0)} to ${fmt(lv.high, 0)}%`, lv.elevated, lv.high], ["High", `${fmt(lv.high, 0)}% or more`, lv.high, Infinity]];
  const band = bands.find(([, , lo, hi]) => s >= lo && s < hi) as [string, string, number, number];
  const levelName = caution && (caution.level === "HIGH" ? "High" : "Elevated");
  const steps = !caution ? null : held
    ? ["It isn't a reason to sell on its own.", "Expect bigger price moves than usual, up and down.", "Check the latest announcements for anything new."]
    : ["Expect bigger price moves than usual, up and down.", "Read the latest results and announcements first.",
      caution.level === "HIGH" ? "If you buy, keep the amount small." : "Set a watchlist trigger to see if shorting keeps growing."];
  return (
    <Card title="Short selling" wide className="short-info">
      {caution
        ? <p className="short-headline"><CautionTag level={caution.level} />{` ${pct(s, 1)} of ${c.asx_code}'s shares are sold short: professional investors are betting the price will fall.`}</p>
        : <p className="short-headline">{`${pct(s, 1)} of ${c.asx_code}'s shares are sold short. ` +
          (s < lv.watch ? "That's normal for the ASX: nothing to worry about." : "That's above normal, but not enough for a caution.")}</p>}
      <ol className="short-scale" aria-label={`Where ${c.asx_code} sits: ${pct(s, 1)} sold short, ${band[0]}`}>
        {bands.map(([name, range, lo, hi]) => {
          const here = s >= lo && s < hi;
          return (
            <li key={name} className={here ? (caution ? "here" : "here calm") : undefined} aria-current={here ? "true" : undefined}>
              <span className="band-name">{name}</span><span className="band-range">{range}</span>
              {here ? <span className="band-here">{`${c.asx_code} ${pct(s, 1)}`}</span> : null}
            </li>
          );
        })}
      </ol>
      {caution && band[0] !== levelName ? <p className="hint">{`Sift rates it ${levelName}, not ${band[0]}, because ` +
        (known(days) && days >= 5 ? `short sellers would need about ${fmt(days, 0)} days of trading to buy back.` : `shorting rose ${fmt(ch, 1)} points in a month.`)}</p> : null}
      {caution && read ? (
        <>
          <h3 className="info-head">Why might they be short?</h3>
          <p className={`short-read ${read.kind.toLowerCase()}`}><strong>{`${read.label}. `}</strong>{read.summary}</p>
          {read.reasons.length ? <ul className="info-steps reasons">{read.reasons.map((t) => <li key={t}>{t}</li>)}</ul> : null}
        </>
      ) : null}
      {steps ? (
        <>
          <h3 className="info-head">{held ? "What it means for you" : "If you're thinking of buying"}</h3>
          <ul className="info-steps">{steps.map((t) => <li key={t}>{t}</li>)}</ul>
        </>
      ) : null}
      <details className="short-details">
        <summary><span className="twisty" aria-hidden="true" />Details and chart</summary>
        <div className="stats fit">
          <StatTile label="Sold short" value={pct(x.short_percent, 2)} cls={caution ? "caution-text" : null} note={`${fmt(x.short_positions, 0)} shares`} />
          <StatTile label="Days to cover" value={known(days) ? fmt(days, 1) : NA} note="shares short / average daily volume" />
          <StatTile label="Change over a month" value={known(ch) ? `${ch > 0 ? "+" : ""}${fmt(ch, 2)} pts` : NA}
            note={!known(ch) ? "needs a month of reports" : ch > 0 ? "more shorted" : ch < 0 ? "less shorted" : "unchanged"} />
        </div>
        {x.history.length >= 2 ? <ChartSlot draw={(w) => lineChart({ series: [{ name: "% of shares sold short", color: "--s1", points: x.history }],
          yFmt: (v) => fmt(v, 1) + "%", label: `${c.asx_code} short interest`, width: w, height: 180 })} /> : null}
        <p className="hint">{"Why heavily shorted shares swing: bad news lands on a crowded bet against the company, so the price can fall fast; " +
          "good news can force short sellers to buy back at once, so it can jump (a short squeeze). Days to cover is how many days of normal trading " +
          `they'd need to buy back: the more days, the sharper a squeeze can be. ASIC report of ${longDate(x.report_date)}, published about four business days later.`}</p>
      </details>
      <p className="hint">A prompt for your own research, not financial advice. <HelpLink id="short-selling" /></p>
    </Card>
  );
}

const cents = (v: number) => (v < 1 ? `${fmt(v * 100, v * 100 % 1 ? 1 : 0)}c` : money(v));
/* How many shares it takes for the dividends to buy a whole new share at
   today's price. Only for companies paying an ordinary dividend now. */
export function DrpCard({ x }: { x: Drp | null }) {
  if (!x) return null;
  const tile = (label: string, need: { shares: number; value: number } | null, note: string) =>
    <StatTile label={label} value={need ? plural(need.shares, "share") : NA} note={need ? `worth ${money(need.value, 0)}; ${note}` : note} />;
  const lp = x.last_payment;
  return (
    <Card title="Dividend reinvestment (DRP)" hint={`Shares you'd need to hold for the dividends to buy a whole new share at today's price of ${money(x.price)}.`}>
      <div className="stats drp-stats">
        {tile("1 new share each payment", x.per_payment, `on the latest dividend of ${cents(lp.amount)} (ex ${longDate(lp.ex_date)})`)}
        {tile("1 new share a year", x.per_year, x.year_total ? `on ${cents(x.year_total)} paid in the last 12 months (${plural(x.payments_in_year, "payment")})` : "no dividend in the last 12 months")}
      </div>
      {x.yours ? <p>{`Your ${fmt(x.yours.units, 0)} shares: each payment buys about ${fmt(x.yours.per_payment, 1)} new ${x.yours.per_payment === 1 ? "share" : "shares"}`}
        {x.yours.per_year !== null ? `, a year about ${fmt(x.yours.per_year, 1)}.` : "."}</p> : null}
      <p className="drp-join"><strong>It isn't automatic. </strong>
        {"Dividends are paid in cash unless you join the DRP through the company's share registry (see the Share registry card). " +
          "To count for a dividend, your choice usually has to reach the registry by the day after the record date. "}<HelpLink id="drp" /></p>
    </Card>
  );
}

function RegistryEditor({ code, x, saved }: { code: string; x: RegistryInfo; saved: (next: RegistryInfo) => void }) {
  const [pick, setPick] = useState(x.registry && x.registry.registry_id ? x.registry.registry_id : x.registry ? "other" : "");
  const [name, setName] = useState(x.registry && !x.registry.registry_id ? x.registry.name : "");
  const msg = useRef<HTMLSpanElement>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      saved(await send<RegistryInfo>("PUT", `/api/admin/company/${code}/registry`, pick === "other" ? { name } : { registry_id: pick || null }));
    } catch (err) { showMessage(msg.current, (err as Error).message, false); }
  };
  return (
    <details className="registry-admin">
      <summary>Change (admin)</summary>
      <form className="registry-edit" onSubmit={submit}>
        <select aria-label="Registry" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">Use what ASX says</option>
          {x.choices.map((o) => <option key={o.registry_id} value={o.registry_id}>{o.name}</option>)}
          <option value="other">Another registry...</option>
        </select>
        <input type="text" maxLength={160} placeholder="Registry name" aria-label="Registry name" value={name}
          onChange={(e) => setName(e.target.value)} hidden={pick !== "other" || undefined} />
        <button type="submit" className="btn small">Save</button>
        <span className="form-msg" role="status" ref={msg} />
      </form>
    </details>
  );
}

export function RegistryCard({ code, info }: { code: string; info: RegistryInfo | null }) {
  const [x, setX] = useState(info);
  if (!x) return null;
  const r = x.registry;
  const source = x.source === "admin" ? "Set by an admin." : x.source === "asx" && x.checked_at ? `From ASX's company details, checked ${longDate(x.checked_at.slice(0, 10))}.` : null;
  return (
    <Card title="Share registry">
      <div>
        {r ? <p className="registry-name strong">{r.name}</p> : <p className="hint">Not known yet: Sift reads it from ASX's company details about once a month.</p>}
        {r && r.portal ? <p><a href={r.portal} target="_blank" rel="noopener noreferrer">{`Log in to ${r.name.split(" (")[0]}'s investor portal ↗`}</a></p> : null}
        {r && r.website && r.website !== r.portal ? <p><a href={r.website} target="_blank" rel="noopener noreferrer">Registry website ↗</a></p> : null}
        <p className="hint">The registry keeps the company's register of shareholders. Log in to see your holding, choose whether dividends are paid in cash or reinvested (DRP), and how leftover cash is handled. <HelpLink id="drp" /></p>
        {source ? <p className="hint">{source}</p> : null}
        {host().isAdmin() ? <RegistryEditor key={JSON.stringify(x.registry)} code={code} x={x} saved={setX} /> : null}
      </div>
    </Card>
  );
}

export function NoticesCard({ list }: { list: Notice[] | null }) {
  return (
    <Card title="Director and substantial holder notices" wide
      hint="From ASX announcements over the last year: directors trading their own company's shares (Appendix 3Y) and holders of 5% or more. On-market buys with the director's own money say the most.">
      {list && list.length ? <ul className="items notice-list">{list.map((n, i) => <NoticeLine key={i} n={n} />)}</ul> : <p className="hint">None in the last year.</p>}
      <HelpLink id="director-trades" />
    </Card>
  );
}

/* ---------- workings: every step of the valuation (gui.py /api/company/{code}/workings) ---------- */
type V = number | string | null;
interface Step { title: string; help_id: string | null; result: V; unit: string; formula: string; inputs: { label: string; value: V; unit: string }[]; note?: string | null }
interface Workings {
  scenario: string | null; scenarios: { scenario_id: string; name: string }[]; estimated_value: number | null; margin_of_safety: number | null;
  action: { action: string; reason: string; flags: string[]; help_id: string };
  valuation: { method: string; help_id: string; why: string; assumptions: { label: string; value: number }[];
    base: { label: string; years: { year: number; value: V }[]; average: V }; unavailable: string | null;
    years: { year: number; flow: V; factor: number; present_value: V }[]; steps: Step[] };
  ratios: Step[]; tests: { name: string; value: number | null; unit: string; rule: string; passed: boolean; help_id: string }[];
  markers: Step[]; score: { total: number; help_id: string };
  sensitivity: { method: string; price: number; discount_rates: number[];
    rows: { growth: number; cells: ({ value: number | null; mos: number; status: string; current?: boolean } | null)[] }[] } | null;
}

export function stepValue(v: V | undefined, unit?: string): string {
  if (v === null || v === undefined) return NA;
  if (typeof v === "string") return v;
  if (unit === "$") return Math.abs(v) >= 100000 ? compact(v) : money(v, Math.abs(v) < 10 ? 3 : 2);
  if (unit === "%") return pct(v, 1);
  if (unit === "x") return fmt(v, 2);
  if (unit === "points") return `${fmt(v, 1)} points`;
  if (Number.isInteger(Number(v)) && Math.abs(v) < 100000) return fmt(v, 0);
  return Math.abs(v) >= 100000 ? new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 2 }).format(v) : fmt(v, 2);
}

function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="steps">{steps.map((st, k) => (
      <li key={k}>
        <div className="step-head"><span className="step-title"><WithHelpLink text={st.title} id={st.help_id} /></span><span className="step-result">{stepValue(st.result, st.unit)}</span></div>
        <div className="step-formula">{st.formula}</div>
        {st.inputs.length ? <div className="step-inputs">{st.inputs.map((i, n) => <span key={n}>{`${i.label} `}<strong>{stepValue(i.value, i.unit)}</strong></span>)}</div> : null}
        {st.note ? <div className="hint">{st.note}</div> : null}
      </li>
    ))}</ol>
  );
}

function Sec({ title, help, children }: { title: string; help: string | null; children: React.ReactNode }) {
  return <section className="work-sec"><h3><WithHelpLink text={title} id={help} /></h3>{children}</section>;
}

const STATUS_CLS: Record<string, string> = { Undervalued: "under", "Fair value": "fair", Overvalued: "over" };

function WorkingsBody({ d, choose }: { d: Workings; choose: (id: string) => void }) {
  const v = d.valuation, base = v.base;
  return (
    <>
      <div className="workings-head">
        <select aria-label="Settings" className="inline-select" value={d.scenarios.find((x) => x.name === d.scenario)?.scenario_id ?? ""} onChange={(e) => choose(e.target.value)}>
          <option value="">Live settings</option>
          {d.scenarios.map((x) => <option key={x.scenario_id} value={x.scenario_id}>{`Scenario: ${x.name}`}</option>)}
        </select>
        <span>{d.scenario ? `Under ${d.scenario}: ` : ""}estimated value <strong>{money(d.estimated_value)}</strong>, margin of safety <strong>{pct(d.margin_of_safety, 1)}</strong>, <ValuationPill mos={d.margin_of_safety} /> <Badge action={d.action.action} /></span>
      </div>
      <Sec title={`Estimated value (${v.method})`} help={v.help_id}>
        <p className="hint">{v.why}</p>
        <div className="step-inputs">{v.assumptions.map((a) => <span key={a.label}>{`${a.label} `}<strong>{pct(a.value, a.value % 1 ? 1 : 0)}</strong></span>)}</div>
        <div className="table-wrap"><table className="grid compact">
          <thead><tr><th>Base year</th><th className="num">{base.label}</th></tr></thead>
          <tbody>
            {base.years.map((y) => <tr key={y.year} className="static"><td>{`FY${y.year}`}</td><td className="num">{stepValue(y.value, "$")}</td></tr>)}
            <tr className="static total"><td>Average (the base)</td><td className="num strong">{stepValue(base.average, "$")}</td></tr>
          </tbody>
        </table></div>
        {v.unavailable ? <p className="empty">{v.unavailable}</p> : (
          <>
            <div className="table-wrap"><table className="grid compact">
              <thead><tr>{["Year", "Cash flow", "Discount factor", "Present value"].map((x, i) => <th key={x} className={i ? "num" : undefined}>{x}</th>)}</tr></thead>
              <tbody>{v.years.map((y) => (
                <tr key={y.year} className="static"><td>{String(y.year)}</td><td className="num">{stepValue(y.flow, "$")}</td>
                  <td className="num">{fmt(y.factor, 4)}</td><td className="num">{stepValue(y.present_value, "$")}</td></tr>
              ))}</tbody>
            </table></div>
            <StepList steps={v.steps} />
          </>
        )}
      </Sec>
      <Sec title="Ratios" help="roe">
        <div className="table-wrap"><table className="grid compact">
          <thead><tr>{["Ratio", "Formula", "Inputs", "Result"].map((x, i) => <th key={x} className={[i === 3 ? "num" : "", i === 2 ? "opt" : ""].join(" ").trim() || undefined}>{x}</th>)}</tr></thead>
          <tbody>{d.ratios.map((st, k) => (
            <tr key={k} className="static"><td><WithHelpLink text={st.title} id={st.help_id} /></td><td className="formula">{st.formula}</td>
              <td className="opt hint">{st.inputs.map((i, n) => `${n ? ", " : ""}${i.label} ${stepValue(i.value, i.unit)}`).join("")}</td>
              <td className="num strong">{stepValue(st.result, st.unit)}</td></tr>
          ))}</tbody>
        </table></div>
      </Sec>
      <Sec title="The four value tests" help="four-value-tests">
        <ul className="checklist">{d.tests.map((t) => (
          <li key={t.name}><span className={`mark ${t.passed ? "pass" : "fail"}`} aria-hidden="true">{t.passed ? "✓" : "✕"}</span>
            <span><WithHelpLink text={`${t.name}: ${t.value === null ? NA : t.unit === "%" ? pct(t.value, 1) : fmt(t.value, 2)} (needs ${t.rule})`} id={t.help_id} /></span></li>
        ))}</ul>
      </Sec>
      <Sec title="Markers" help="earnings-quality"><StepList steps={d.markers} /></Sec>
      <Sec title="Suggested action" help={d.action.help_id}>
        <p><Badge action={d.action.action} /> {d.action.reason}</p>
        {d.action.flags.length ? <ul className="flags">{d.action.flags.map((f) => <li key={f}>{f}</li>)}</ul> : <p className="hint">No red flags.</p>}
        <p className="hint">{`Score ${d.score.total} of 30. `}<HelpLink id={d.score.help_id} /></p>
      </Sec>
      {d.sensitivity ? (
        <Sec title={`Sensitivity: estimated value at other rates (${d.sensitivity.method})`} help="sensitivity-grid">
          <p className="hint">{`Rows: growth rate. Columns: discount rate. Each cell: estimated value and margin of safety at today's price of ${money(d.sensitivity.price)}. The outlined cell is the setting in use.`}</p>
          <div className="table-wrap"><table className="grid compact sens">
            <thead><tr><th>Growth \ discount</th>{d.sensitivity.discount_rates.map((r) => <th key={r} className="num">{pct(r, 0)}</th>)}</tr></thead>
            <tbody>{d.sensitivity.rows.map((row) => (
              <tr key={row.growth} className="static"><th scope="row">{pct(row.growth, 1)}</th>
                {row.cells.map((c, k) => (
                  <td key={k} className={`num${c && c.current ? " current" : ""}`}>
                    {!c || c.value === null ? NA : <><div className="strong">{money(c.value)}</div><span className={`pill ${STATUS_CLS[c.status] || "none"}`}>{pct(c.mos, 0)}</span></>}
                  </td>
                ))}</tr>
            ))}</tbody>
          </table></div>
        </Sec>
      ) : null}
    </>
  );
}

export function WorkingsCard({ code }: { code: string }) {
  const [state, setState] = useState<{ d?: Workings; error?: string; loading?: boolean }>({});
  const [loaded, setLoaded] = useState(false);
  const load = async (scenario = "") => {
    setState({ loading: true });
    try {
      setState({ d: await getJSON<Workings>(`/api/company/${encodeURIComponent(code)}/workings${scenario ? `?scenario=${scenario}` : ""}`) });
    } catch (err) { setState({ error: (err as Error).message }); }
  };
  return (
    <Card title="Workings and what-if" wide hint="Every step of the valuation, with this company's numbers.">
      <details className="axis-block workings-toggle" onToggle={(e) => { if ((e.currentTarget as HTMLDetailsElement).open && !loaded) { setLoaded(true); load(); } }}>
        <summary><span className="twisty" aria-hidden="true" /><span className="axis-name">Show workings</span></summary>
        <div className="workings">
          {state.loading ? <p className="loading">Working it out...</p> : state.error ? <p className="error">{state.error}</p>
            : state.d ? <WorkingsBody d={state.d} choose={(x) => load(x)} /> : null}
        </div>
      </details>
      <p className="hint" style={{ marginTop: 8 }}>Settings behind these steps: <a href="#/admin">Model and rules</a>. <HelpLink id="show-workings" /></p>
    </Card>
  );
}
