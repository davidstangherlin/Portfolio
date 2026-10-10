// Track record pieces shared by the Track record page and (later) the
// dashboard: one verdict row per action and the "Track record" card.
import { edgeBar, type EdgeInput } from "../charts/edgeBar";
import type { Ticks } from "../charts/ticks";
import { fmt, longDate, plural, toDate } from "../lib/format";
import type { ActionResult, RuleTest, TrackingStatus } from "../lib/types";
import { Badge } from "./bits";
import { Card } from "./Card";
import { ChartSlot } from "./ChartSlot";

export const horizonText = (m: number): string => (m === 1 ? "1 month" : `${m} months`);
export const points = (v: number): string => `${fmt(Math.abs(v), 1)} point${Math.abs(v) === 1 ? "" : "s"}`;

export function VerdictPill({ t }: { t: RuleTest }) {
  const [cls, icon] = t.intended === true ? ["good", "✓"] : t.intended === false ? ["bad", "✕"]
    : t.kind === "NEEDS_MORE" ? ["wait", "…"] : t.kind === "UNCLEAR" ? ["wait", "~"] : ["wait", "–"];
  return <span className={`vpill ${cls}`}><span aria-hidden="true">{icon}</span>{t.label}</span>;
}

/* One row per action: its verdict (more than luck?), one plain sentence and,
   on the Track record page, a bar of where its true edge most likely sits. */
export function VerdictLine({ a, months, domain }: { a: ActionResult; months: number; domain: Ticks | null }) {
  const beat = a.avg_excess >= 0, t = a.test;
  const rate = a.beat_rate === null ? null : beat ? a.beat_rate : 100 - a.beat_rate;
  const luck = t.kind === "NEEDS_MORE" ? ` Too early to tell: Sift needs ${fmt(t.min_calls, 0)} calls and has ${fmt(a.signals, 0)}.`
    : t.kind === "UNCLEAR" ? ` That could easily be luck: ${t.luck}.` : ` That's unlikely to be luck: ${t.luck}.`;
  return (
    <li className="rule-row">
      <div className="rule-head"><Badge action={a.action} /><VerdictPill t={t} /></div>
      <div className="rule-body">
        <p className="verdict-text">
          {`${a.action} calls ${beat ? "beat" : "trailed"} the average screened share by ${points(a.avg_excess)} over ${horizonText(months)}` +
            (rate === null ? "." : `; ${fmt(rate, 0)}% of ${fmt(a.signals, 0)} ${beat ? "beat" : "trailed"} it.`) + luck}
        </p>
        {t.low !== null && domain ? <ChartSlot draw={(w) => edgeBar(a as EdgeInput, domain, w)} /> : null}
      </div>
    </li>
  );
}

export function ResultsTimeline({ t }: { t: TrackingStatus }) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return (
    <ul className="timeline">
      {t.results_due.map((r) => {
        const days = Math.round((toDate(r.date).getTime() - today.getTime()) / 86400000);
        return <li key={r.months}><span>{`${r.months}-month results`}</span>
          <span>{days > 0 ? `${longDate(r.date)} (in ${plural(days, "day")})` : `from ${longDate(r.date)}`}</span></li>;
      })}
    </ul>
  );
}

export function TrackingCard({ t, withLink = true }: { t: TrackingStatus; withLink?: boolean }) {
  return (
    <Card title="Track record">
      {t.first_date ? (
        <>
          <p className="hint">{`Recording since ${longDate(t.first_date)}: ${plural(t.days_recorded, "night")}, ${plural(t.signals_recorded, "signal")}.`}</p>
          {t.headline ? <ul className="verdict rules compact"><VerdictLine a={t.headline} months={t.headline.horizon_months} domain={null} /></ul> : null}
          <ResultsTimeline t={t} />
        </>
      ) : (
        <p className="empty">Recording starts with the next nightly run. Each night Sift records every company's suggested action, valuation and score, so they can be checked later against what the share price did.</p>
      )}
      {withLink ? <p className="card-foot"><a href="#/track-record">Track record →</a></p> : null}
    </Card>
  );
}
