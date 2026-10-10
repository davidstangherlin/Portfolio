// The company page's answer (gui.py company_payload()). Only the fields the
// page reads are named; the rest pass through untyped.
import type { DividendMarker, Point } from "../../charts/lineChart";
import type { AxisDetail } from "../../charts/wheel";
import type { Notice } from "../../components/notices";
import type { WatchEntry } from "../../components/watch";
import type { Health } from "../../lib/types";

type N = number | null;
export interface Rating { rating_month: string; strong_buy: number; buy: number; hold: number; sell: number; strong_sell: number }
export interface HolderRow { holder: string; shares: N; percent_held: N; value_now: N; percent_change: N; date_reported: string | null }
export interface Insights {
  fetched_at: string; ratings: Rating[]; recommendation_key: string | null; recommendation_mean: N;
  target_mean: N; target_median: N; target_low: N; target_high: N; analyst_count: N;
  insiders_percent: N; institutions_percent: N; institutions_float_percent: N; institutions_count: N;
  funds: HolderRow[]; institutions: HolderRow[];
}
export interface Company {
  asx_code: string; company_name: string | null; sector: string | null; industry: string | null; country: string | null;
  action: string; action_reason: string; current_price: N; as_of_date: string; dcf_intrinsic_value: N; graham_number: N;
  margin_of_safety_percent: N; valuation_method: string | null; statements_issue: string | null;
  business_summary: string | null; business_summary_short: string | null;
  earnings_quality: string | null; cash_conversion: N; price_signal: string | null; price_vs_200d: N; dividend_trend: string | null;
  fundamentals_trend: string | null; margin_of_safety_trend: N; trap_risk: string | null; data_confidence: string | null;
  pe_ratio: N; pb_ratio: N; price_to_fcf: N; ev_to_ebit: N; roe: N; roic: N; debt_to_equity: N; uncapped_dividend_yield: N;
  grossed_up_dividend_yield: N; payout_ratio: N; financial_currency: string | null; trading_currency: string | null;
  days_to_cover: N; insights: Insights | null; notices: Notice[] | null;
}
export interface Report {
  fiscal_year: number; report_date: string; revenue: N; net_profit_after_tax: N; free_cash_flow: N; dividends_per_share: N;
  abnormal_distributions_per_share: N; reporting_currency: string | null; fx_rate: N;
}
export interface Chance { label: string; level: number; above_today_percent: number; already_reached: boolean; chance: N; words: { in_ten: number; word: string; text: string } | null }
export interface Statistics { volatility_percent: N; years_of_prices: number; observations: number; beta: N; market_code: string | null; chances: Chance[] }
export interface ShortInterest { short_percent: number; short_positions: number; change_points: N; report_date: string; history: Point[] }
export interface Registry { registry_id: string | null; name: string; portal: string | null; website: string | null }
export interface RegistryInfo { registry: Registry | null; source: string | null; checked_at: string | null; choices: { registry_id: string; name: string }[] }
export interface Drp {
  price: number; last_payment: { amount: number; ex_date: string }; per_payment: { shares: number; value: number } | null;
  per_year: { shares: number; value: number } | null; year_total: N; payments_in_year: number;
  yours: { units: number; per_payment: number; per_year: N } | null;
}
export interface CompanyData {
  company: Company; axes: string[]; checks_per_axis: number; scores: Record<string, AxisDetail>;
  tests: { name: string; value: N; unit: string; rule: string; passed: boolean }[]; flags: string[];
  short_caution: { level: string } | null; short_read: { kind: string; label: string; summary: string; reasons: string[] } | null;
  short_levels: { watch: number; elevated: number; high: number }; short_interest: ShortInterest | null;
  model: { method: string; growth_rate: number; stage1_years: number; terminal_growth_rate: number; discount_rate: number } | null;
  watchlists: WatchEntry[]; position: { units: number; cost_base: number; next_discount_date: string | null; units_pending_discount: number } | null;
  prices: Point[]; volumes?: Point[]; dividends?: Omit<DividendMarker, "date">[]; mos_history: Point[]; reports: Report[];
  statistics: Statistics | null; drp: Drp | null; registry: RegistryInfo | null; health?: Health | null;
}
