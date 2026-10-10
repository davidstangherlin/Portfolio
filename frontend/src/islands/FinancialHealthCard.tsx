// Financial health on the company page (docs/kb/features/financial-health.md):
// the Piotroski F-Score and the Altman Z-Score, in plain words first.
// Sift's first React card (docs/kb/decisions/adr-018-react-typescript-pages.md).
import { Card } from "../components/Card";
import { Checklist } from "../components/Checklist";
import { HelpLink } from "../components/HelpLink";
import { WorkedOut } from "../components/WorkedOut";
import { fmt } from "../lib/format";
import { host } from "../lib/host";
import type { Health } from "../lib/types";

const F_PILL = { STRONG: ["good", "✓"], MIDDLING: ["wait", "~"], WEAK: ["bad", "✕"], NOT_ENOUGH: ["wait", "…"] } as const;
const Z_PILL = { SAFE: ["good", "✓"], GREY: ["wait", "~"], DISTRESS: ["bad", "!"] } as const;
const Z_BANDS: [string, string, "DISTRESS" | "GREY" | "SAFE"][] =
  [["Distress", "below 1.81", "DISTRESS"], ["Grey", "1.81 to 2.99", "GREY"], ["Safe", "above 2.99", "SAFE"]];
const Z_PART_NAMES: Record<string, string> = {
  working_capital: "Working capital / assets (x 1.2)", retained_earnings: "Retained earnings / assets (x 1.4)",
  ebit: "EBIT / assets (x 3.3)", market_value: "Market value / liabilities (x 0.6)", sales: "Sales / assets (x 1.0)",
};

function Pill({ kind, icon, text }: { kind: string; icon: string; text: string }) {
  return <span className={`vpill ${kind}`}><span aria-hidden="true">{icon}</span>{text}</span>;
}

export function FinancialHealthCard({ code, health }: { code: string; health: Health | null }) {
  if (!health) {
    return <Card title="Financial health" hint="Worked out each night from the latest annual reports; not available for this company yet." />;
  }
  if (health.excluded_reason) {
    return (
      <Card title="Financial health">
        <p>Not scored: the F-Score and Z-Score weren't designed for {health.excluded_reason}, whose balance sheets work differently. <HelpLink id="financial-health" /></p>
      </Card>
    );
  }
  const f = health.f_level ? F_PILL[health.f_level] : null;
  const z = health.z_zone ? Z_PILL[health.z_zone] : null;
  const missing = health.f_checks !== null ? 9 - health.f_checks : 9;
  return (
    <Card title="Financial health" className="financial-health">
      <div className="health-block">
        <p className="health-head">
          <span className="health-score">{health.f_score ?? "–"}<small> / 9</small></span>
          {f ? <Pill kind={f[0]} icon={f[1]} text={health.f_words ?? ""} /> : null}
          <span className="health-name">Piotroski F-Score <HelpLink id="financial-health" /></span>
        </p>
        <p>
          {health.f_level === "NOT_ENOUGH"
            ? `Not enough data yet: Sift could make ${health.f_checks ?? 0} of the 9 checks for ${code}.`
            : `${code} passed ${health.f_score} of the 9 checks that separate strengthening businesses from weakening ones.`}
          {missing > 0 && health.f_level !== "NOT_ENOUGH"
            ? ` Sift has the data for ${health.f_checks} of them; the rest fill in as statements refresh.` : ""}
        </p>
        <Checklist items={health.f_detail.map((c) => ({ label: c.label, passed: c.passed, title: c.rule }))} />
      </div>

      <div className="health-block">
        <p className="health-head">
          <span className="health-score">{health.z_score === null ? "–" : fmt(health.z_score, 1)}</span>
          {z ? <Pill kind={z[0]} icon={z[1]} text={health.z_words ?? ""} /> : null}
          <span className="health-name">Altman Z-Score</span>
        </p>
        {health.z_zone ? (
          <>
            <p>{health.z_meaning}</p>
            <ol className="short-scale zone-scale" aria-label={`Where ${code} sits: ${health.z_words}`}>
              {Z_BANDS.map(([name, range, key]) => {
                const here = key === health.z_zone;
                return (
                  <li key={key} className={here ? (key === "DISTRESS" ? "here" : "here calm") : undefined} aria-current={here ? "true" : undefined}>
                    <span className="band-name">{name}</span><span className="band-range">{range}</span>
                    {here ? <span className="band-here">{code} {fmt(health.z_score, 1)}</span> : null}
                  </li>
                );
              })}
            </ol>
          </>
        ) : (
          <p className="hint">Needs current assets, current liabilities and retained earnings, which Sift is adding as each company's statements refresh (weekly).</p>
        )}
      </div>

      <WorkedOut helpId="financial-health" paragraphs={[
        `From ${code}'s annual reports${health.fiscal_year ? ` (latest ${health.fiscal_year})` : ""}. The F-Score (Piotroski, 2000) gives a point for each sign of strength: profit, cash flow, improving returns, profit backed by cash, falling debt, a better short-term position, no new shares, a better gross margin and more sales per dollar of assets. 7 to 9 is Strong, 4 to 6 Middling, 0 to 3 Weak. A check without data neither passes nor fails.`,
        "The Z-Score (Altman, 1968) combines five balance-sheet ratios into one figure. Above 2.99 is the safe zone, below 1.81 the distress zone. A share in the distress zone gets a caution beside its action; the action itself doesn't change.",
      ]}>
        {host().isAdmin() && health.z_score !== null ? (
          <p className="hint">Admin: {Object.keys(Z_PART_NAMES).map((k) => `${Z_PART_NAMES[k]} ${health.z_parts[k] == null ? "n/a" : fmt(health.z_parts[k], 3)}`).join("; ")}.</p>
        ) : null}
      </WorkedOut>
      <p className="hint">A prompt for your own research, not financial advice.</p>
    </Card>
  );
}
