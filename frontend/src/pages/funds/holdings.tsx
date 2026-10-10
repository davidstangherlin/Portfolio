// What a fund holds (§26.3): Yahoo Finance's fund data.
import { Card } from "../../components/Card";
import { HelpLink } from "../../components/HelpLink";
import { fmt, longDate, pct } from "../../lib/format";

export interface Profile {
  description: string | null; description_short: string | null; fetched_at: string;
  holdings: { name: string; symbol: string | null; weight_percent: number | null }[] | null; top10_percent: number | null;
  sector_weightings: Record<string, number> | null; bond_ratings: Record<string, number> | null;
  stock_percent: number | null; bond_percent: number | null; cash_percent: number | null; other_percent: number | null;
  duration_years: number | null; maturity_years: number | null;
  look_through_symbol: string | null; look_through_name: string | null; look_through_percent: number | null;
}

const SECTOR_NAMES: Record<string, string> = { realestate: "Real estate", consumer_cyclical: "Consumer cyclical", basic_materials: "Basic materials",
  consumer_defensive: "Consumer defensive", technology: "Technology", communication_services: "Communication services",
  financial_services: "Financial services", utilities: "Utilities", industrials: "Industrials", energy: "Energy", healthcare: "Health care" };
const RATING_ORDER: [string, string][] = [["us_government", "Government"], ["aaa", "AAA"], ["aa", "AA"], ["a", "A"], ["bbb", "BBB"], ["bb", "BB"],
  ["b", "B"], ["below_b", "Below B"], ["other", "Not rated / other"]];
const sectorName = (k: string) => SECTOR_NAMES[k] || (k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " "));

/* Horizontal bars, one hue, value labels beside each (magnitude, not identity). */
function BarList({ items, max }: { items: [string, number][]; max?: number }) {
  const top = max || Math.max(...items.map(([, v]) => v), 1);
  return (
    <div className="bar-list">{items.map(([label, v]) => (
      <div key={label} className="bar-row" title={`${label}: ${fmt(v, 1)}%`}>
        <span className="bar-label">{label}</span>
        <span className="bar-track"><span className="bar-fill" style={{ width: `${Math.max(0.5, (v / top) * 100)}%` }} /></span>
        <span className="bar-value">{pct(v, 1)}</span>
      </div>
    ))}</div>
  );
}

function mixParts(p: Profile) {
  return ([["Shares", p.stock_percent, "--s1"], ["Bonds", p.bond_percent, "--s2"], ["Cash", p.cash_percent, "--s3"], ["Other", p.other_percent, "--neutral"]] as [string, number | null, string][])
    .filter((x): x is [string, number, string] => x[1] !== null && x[1] > 0);
}
function AssetMix({ parts }: { parts: [string, number, string][] }) {
  return (
    <div className="asset-mix">
      <div className="mix-bar" role="img" aria-label={parts.map(([n, v]) => `${n} ${fmt(v, 1)}%`).join(", ")}>
        {parts.map(([n, v, c]) => <span key={n} className="mix-seg" style={{ flexGrow: v, background: `var(${c})` }} title={`${n}: ${fmt(v, 1)}%`} />)}
      </div>
      <div className="legend">{parts.map(([n, v, c]) => <span key={n}><span className="key rect" style={{ background: `var(${c})` }} />{`${n} ${pct(v, 1)}`}</span>)}</div>
    </div>
  );
}

export function FundHoldingsCard({ p, lic, code }: { p: Profile | null; lic: boolean; code: string }) {
  const title = "What it holds";
  if (!p) return <Card title={title} hint="Not fetched yet. Sift fetches each fund's holdings and sectors from Yahoo Finance weekly, so this fills in within a week." />;
  const holdings = p.holdings || [], sectors = Object.entries(p.sector_weightings || {}).sort((a, b) => b[1] - a[1]), ratings = p.bond_ratings || {};
  const note = <p className="card-foot hint">{`Yahoo Finance (Morningstar data), fetched ${longDate(p.fetched_at.slice(0, 10))}. Refreshed weekly. `}<HelpLink id="fund-holdings" /></p>;
  if (!holdings.length && !sectors.length && !p.stock_percent && !p.bond_percent) {
    return <Card title={title} hint={lic
      ? "Yahoo Finance lists LICs as companies, so it has no holdings or sector breakdown for them. Each LIC names its top holdings in its monthly NTA report, on its own website or the ASX announcements page."
      : "Yahoo Finance has no holdings or sector breakdown for this fund."}>{note}</Card>;
  }
  const ratingRows = RATING_ORDER.filter(([k]) => ratings[k] > 0).map(([k, label]) => [label, ratings[k]] as [string, number]);
  const bondStats = [p.duration_years !== null ? `Duration ${fmt(p.duration_years, 1)} years` : null,
    p.maturity_years !== null ? `average maturity ${fmt(p.maturity_years, 1)} years` : null].filter(Boolean);
  const parts = mixParts(p);
  const holdingsTable = holdings.length ? (
    <div>
      <h3 className="holders-head">Top 10 holdings</h3>
      <div className="table-wrap"><table className="grid compact">
        <thead><tr><th>Holding</th><th className="opt">Code</th><th className="num">% of fund</th></tr></thead>
        <tbody>{holdings.map((x, i) => <tr key={i} className="static"><td className="holder-name">{x.name}</td><td className="opt mono">{x.symbol || ""}</td><td className="num">{pct(x.weight_percent, 2)}</td></tr>)}</tbody>
      </table></div>
      {p.top10_percent !== null ? <p className="hint">{`The top 10 are ${pct(p.top10_percent, 1)} of the fund.`}</p> : null}
    </div>
  ) : null;
  const sectorBlock = sectors.length ? <div><h3 className="holders-head">Sectors</h3><BarList items={sectors.map(([k, v]) => [sectorName(k), v])} /></div> : null;
  const bondBlock = ratingRows.length || bondStats.length ? (
    <div><h3 className="holders-head">Bonds</h3>
      {bondStats.length ? <p className="hint">{bondStats.join(", ") + "."}</p> : null}
      {ratingRows.length ? <BarList items={ratingRows} max={100} /> : null}</div>
  ) : null;
  return (
    <Card title={title} wide>
      {parts.length ? <><h3 className="holders-head">Asset mix</h3><AssetMix parts={parts} /></> : null}
      {p.look_through_symbol ? <p className="hint note">{`${code} puts ${pct(p.look_through_percent, 2)} of its money into ${p.look_through_name} (${p.look_through_symbol}), ` +
        "so these are that fund's largest holdings and sectors, shown as a share of this one."}</p> : null}
      <div className="holdings-grid">{holdingsTable}{sectorBlock || bondBlock}{sectorBlock ? bondBlock : null}</div>
      {note}
    </Card>
  );
}
