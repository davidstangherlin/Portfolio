// The shapes of Sift's JSON answers that React components read (gui.py).
export interface HealthCheck { key: string; label: string; rule: string; passed: boolean | null }
export interface Health {
  fiscal_year: number | null;
  excluded_reason: string | null;
  f_score: number | null;
  f_checks: number | null;
  f_level: "STRONG" | "MIDDLING" | "WEAK" | "NOT_ENOUGH" | null;
  f_words: string | null;
  f_detail: HealthCheck[];
  z_score: number | null;
  z_zone: "SAFE" | "GREY" | "DISTRESS" | null;
  z_words: string | null;
  z_meaning: string | null;
  z_parts: Record<string, number | null>;
}

// Track record (src/tracking/report.py, src/analytics/rules.py)
export interface RuleTest {
  kind: "BEATING" | "TRAILING" | "UNCLEAR" | "NEEDS_MORE" | string; label: string; intended: boolean | null;
  low: number | null; high: number | null; t: number | null; p_value: number | null; q_value?: number | null;
  luck: string | null; min_calls: number; level?: number;
}
export interface ActionResult { action: string; signals: number; avg_excess: number; beat_rate: number | null; test: RuleTest; horizon_months?: number }
export interface Signal {
  asx_code: string; company_name: string | null; watchlists?: string[]; action: string;
  [key: string]: unknown;
}
export interface TrackingStatus {
  first_date: string | null; days_recorded: number; signals_recorded: number;
  results_due: { months: number; date: string }[]; headline?: ActionResult & { horizon_months: number } | null;
}
export interface TrackRecord {
  horizons: number[];
  verdict: Record<number, { actions: ActionResult[]; order: { status: string } }>;
  monthly: { month: string; action: string; horizon_months: number; avg_excess: number; signals: number }[];
  status: TrackingStatus;
  rules: { too_early_below: number; solid_above: number; margin_of_safety: number; purchase_window_days: number; missed_excess: number };
  actionable: { new: Signal[]; open: Signal[]; moved_on: Signal[] };
  proven: { proven: boolean; horizon: number; actions: string[] };
  missed: Signal[]; saved: Signal[];
  version: string | null; version_label?: string | null;
}
