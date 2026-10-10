// Portfolio pieces shared by the portfolio pages and the dashboard.
import { fmt } from "../../lib/format";

export interface TaxType { tax_type: string; label: string; discount_rate: number }
export interface PortfolioSummary {
  portfolio_id: string; name: string; archived: boolean; tax_type: string; tax_type_label: string; discount_rate: number;
  holdings: number; open_parcels: number; sales: number; value: number | null; gain: number | null; day_change: number | null;
  sections?: Record<string, { holdings: number }> | null;
}
export const discountText = (rate: number) => (rate > 0 ? `${fmt(rate * 100, rate * 100 % 1 ? 1 : 0)}% CGT discount` : "no CGT discount");
export const portfolioHref = (p: { portfolio_id: string }) => `#/portfolio/${p.portfolio_id}`;
