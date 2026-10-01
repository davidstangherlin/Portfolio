"""Orchestrates computing a `valuation_metrics` row for a company from its
latest `daily_prices` and `financial_reports` data, and upserting it.

Shares outstanding are not stored directly in the schema. They are derived
from the latest daily price's `market_cap / close_price` (the most direct
figure we have), falling back to `net_profit_after_tax / eps` when a
market cap isn't available. `current_ratio` is intentionally left `None`:
the schema stores `total_assets`/`total_liabilities` but not the
current (short-term) split, so a true current ratio cannot be derived
without adding those columns.

The DCF's free cash flow base is a `fcf_average_years`-year simple mean
(default 3) across the most recent `FY` reports, not just the single
latest year. This was a deliberate fix (2026-10-02, see docs/AS_BUILT.md
§8.4) after live data showed how unstable a single-year FCF base makes
the DCF: a company with a 3x swing in FCF across 4 years saw its margin
of safety swing from +34% to -10% depending only on growth/discount
assumptions, because the entire projection was anchored to one year's
figure. Every other metric (ROE, D/E, P/E, dividend yield, Graham
Number, ...) still uses only the single latest `FY` report, matching
standard point-in-time ratio practice - only the DCF base is averaged.

Financial Services and Real Estate companies (`_SECTOR_AWARE_SECTORS`) use
a Dividend Discount Model (`src/valuation/ddm.py`) instead of the FCF-based
DCF for their intrinsic value, stored in the same `dcf_intrinsic_value`
column with `valuation_method` recording which model actually ran ('DCF'
or 'DDM', NULL if neither could be computed). See docs/AS_BUILT.md
known-issue #8.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Company, DailyPrice, FinancialReport, ValuationMetric
from src.valuation import dcf as dcf_module
from src.valuation import ddm as ddm_module
from src.valuation.dividends import dividend_yields
from src.valuation.graham import book_value_per_share, graham_number

logger = logging.getLogger(__name__)


DEFAULT_FCF_AVERAGE_YEARS = 3

# Sectors where a standard FCF-based DCF isn't meaningful (known-issue #8):
# these companies' "free cash flow" is dominated by balance-sheet movements
# (loan books, policy reserves, property revaluations) rather than
# reinvestment capex, so they're priced with a Dividend Discount Model
# instead - see src/valuation/ddm.py. Spelled exactly as yfinance's
# `.info["sector"]` returns them for ASX-listed companies.
_SECTOR_AWARE_SECTORS = {"Financial Services", "Real Estate"}


@dataclass
class ValuationInputs:
    company: Company
    price: DailyPrice
    report: FinancialReport  # latest FY report - drives every metric except the DCF/DDM base
    shares_outstanding: Decimal | None
    dcf_free_cash_flow: Decimal | None  # mean FCF across the last fcf_average_years FY reports
    ddm_dividend_per_share: Decimal | None  # mean DPS across the same window, for sector-aware companies


def _latest_price(session: Session, company_id) -> DailyPrice | None:
    stmt = (
        select(DailyPrice)
        .where(DailyPrice.company_id == company_id)
        .order_by(DailyPrice.price_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _last_n_annual_reports(session: Session, company_id, n: int) -> list[FinancialReport]:
    """Up to `n` most recent `FY` reports, newest first."""
    stmt = (
        select(FinancialReport)
        .where(FinancialReport.company_id == company_id, FinancialReport.period_type == "FY")
        .order_by(FinancialReport.fiscal_year.desc())
        .limit(max(n, 1))
    )
    return list(session.execute(stmt).scalars())


def _average_free_cash_flow(reports: list[FinancialReport]) -> Decimal | None:
    """Simple mean of free_cash_flow across whatever reports have a value
    (gracefully handles fewer than the requested number of years, or gaps).
    Returns None only if none of the reports have a usable figure."""
    values = [r.free_cash_flow for r in reports if r.free_cash_flow is not None]
    if not values:
        return None
    return sum(values) / Decimal(len(values))


def _average_dividend_per_share(reports: list[FinancialReport]) -> Decimal | None:
    """Same multi-year averaging as `_average_free_cash_flow`, but on
    dividends_per_share - the DDM base for sector-aware companies (see
    `_SECTOR_AWARE_SECTORS`). Using the same window as the DCF's FCF
    average keeps the two paths consistent and equally resistant to a
    single volatile year (e.g. a special dividend - see payout_ratio and
    docs/AS_BUILT.md known-issue #14 for a case this matters)."""
    values = [r.dividends_per_share for r in reports if r.dividends_per_share is not None]
    if not values:
        return None
    return sum(values) / Decimal(len(values))


def _estimate_shares_outstanding(price: DailyPrice, report: FinancialReport) -> Decimal | None:
    if price.market_cap and price.close_price:
        return price.market_cap / price.close_price
    if report.net_profit_after_tax and report.eps and report.eps != 0:
        return report.net_profit_after_tax / report.eps
    return None


def gather_inputs(
    session: Session, company: Company, fcf_average_years: int = DEFAULT_FCF_AVERAGE_YEARS
) -> ValuationInputs | None:
    price = _latest_price(session, company.company_id)
    reports = _last_n_annual_reports(session, company.company_id, fcf_average_years)
    if price is None or not reports:
        logger.warning(
            "Skipping %s: missing %s", company.asx_code,
            "price and financial data" if price is None and not reports
            else "price data" if price is None else "financial report data",
        )
        return None

    report = reports[0]  # latest - used for everything except the DCF/DDM base
    shares_outstanding = _estimate_shares_outstanding(price, report)
    dcf_free_cash_flow = _average_free_cash_flow(reports)
    ddm_dividend_per_share = _average_dividend_per_share(reports)
    return ValuationInputs(
        company=company,
        price=price,
        report=report,
        shares_outstanding=shares_outstanding,
        dcf_free_cash_flow=dcf_free_cash_flow,
        ddm_dividend_per_share=ddm_dividend_per_share,
    )


def compute_metrics(
    inputs: ValuationInputs,
    *,
    growth_rate: Decimal | None = None,
    discount_rate: Decimal = dcf_module.DEFAULT_DISCOUNT_RATE,
    terminal_growth_rate: Decimal = dcf_module.DEFAULT_TERMINAL_GROWTH_RATE,
    stage1_years: int = dcf_module.DEFAULT_STAGE1_YEARS,
) -> dict:
    price = inputs.price
    report = inputs.report
    shares = inputs.shares_outstanding
    sector_aware = inputs.company.sector in _SECTOR_AWARE_SECTORS

    # growth_rate is the one assumption that genuinely differs by model:
    # dividend growth (DDM, Financial Services/Real Estate) is typically
    # steadier/lower than FCF growth (DCF, everywhere else), so leaving it
    # unset picks each model's own default rather than silently applying
    # the DCF's 8% to dividend growth too. An explicit --growth-rate on the
    # CLI still applies uniformly to whichever model runs, as before.
    if growth_rate is None:
        growth_rate = ddm_module.DEFAULT_GROWTH_RATE if sector_aware else dcf_module.DEFAULT_GROWTH_RATE

    bvps = book_value_per_share(report.total_equity, shares)
    graham = graham_number(report.eps, bvps)

    pe_ratio = price.close_price / report.eps if report.eps and report.eps != 0 else None
    pb_ratio = price.close_price / bvps if bvps else None

    fcf_per_share = report.free_cash_flow / shares if report.free_cash_flow and shares else None
    price_to_fcf = price.close_price / fcf_per_share if fcf_per_share else None

    enterprise_value = None
    ev_to_ebit = None
    if price.market_cap is not None:
        enterprise_value = price.market_cap + (report.total_debt or Decimal("0")) - (report.cash_and_equivalents or Decimal("0"))
        if report.ebit:
            ev_to_ebit = enterprise_value / report.ebit

    roe = (report.net_profit_after_tax / report.total_equity * 100) if report.net_profit_after_tax and report.total_equity else None

    invested_capital = None
    roic = None
    if report.net_profit_after_tax is not None and report.total_debt is not None and report.total_equity is not None:
        invested_capital = report.total_debt + report.total_equity - (report.cash_and_equivalents or Decimal("0"))
        if invested_capital and invested_capital != 0:
            roic = report.net_profit_after_tax / invested_capital * 100

    debt_to_equity = (report.total_debt / report.total_equity) if report.total_debt is not None and report.total_equity else None

    yields = dividend_yields(
        report.dividends_per_share, price.close_price, report.franking_percentage, report.corporate_tax_rate
    )

    # payout_ratio flags a likely special/one-off dividend being read as a
    # sustainable yield: added 2026-10-02 after TWR surfaced at 500-ticker
    # scale with a 106.85% "yield" driven by a single year's dividend at
    # 519% of EPS - not a repeatable income signal. Same NUMERIC(6,2)
    # overflow concern as margin_of_safety_percent (§valuation_metrics
    # schema), so the same sanity cap applies: an extreme result (near-zero
    # or negative EPS against a real dividend) returns None rather than a
    # number that would crash the upsert.
    payout_ratio = None
    if report.dividends_per_share and report.eps and report.eps > 0:
        payout_ratio = (report.dividends_per_share / report.eps) * 100
        if abs(payout_ratio) > Decimal("5000"):
            payout_ratio = None

    # Sector-aware intrinsic valuation (known-issue #8): Financial Services
    # and Real Estate companies are priced with a Dividend Discount Model
    # instead of the standard FCF-based DCF, since their "free cash flow"
    # is dominated by balance-sheet movements rather than reinvestment
    # capex and so isn't a meaningful DCF input - previously this meant
    # these companies almost never got a margin-of-safety figure at all.
    # `valuation_method` records which model (if either) actually ran, so
    # the screener and any downstream review can tell the two apart rather
    # than treating every dcf_intrinsic_value as the same kind of number.
    dcf_intrinsic_value = None
    valuation_method = None
    if sector_aware:
        base_dividend = inputs.ddm_dividend_per_share  # fcf_average_years-year mean DPS
        if base_dividend and base_dividend > 0:
            ddm_result = ddm_module.two_stage_ddm(
                base_dividend_per_share=base_dividend,
                growth_rate=growth_rate,
                stage1_years=stage1_years,
                terminal_growth_rate=terminal_growth_rate,
                discount_rate=discount_rate,
            )
            dcf_intrinsic_value = ddm_result.intrinsic_value_per_share
            valuation_method = "DDM"
    else:
        dcf_fcf = inputs.dcf_free_cash_flow  # fcf_average_years-year mean, not just the latest FY
        if dcf_fcf and dcf_fcf > 0 and shares:
            dcf_result = dcf_module.two_stage_dcf(
                base_fcf=dcf_fcf,
                shares_outstanding=shares,
                cash_and_equivalents=report.cash_and_equivalents or Decimal("0"),
                total_debt=report.total_debt or Decimal("0"),
                growth_rate=growth_rate,
                stage1_years=stage1_years,
                terminal_growth_rate=terminal_growth_rate,
                discount_rate=discount_rate,
            )
            dcf_intrinsic_value = dcf_result.intrinsic_value_per_share
            valuation_method = "DCF"

    margin_of_safety = dcf_module.margin_of_safety_percent(dcf_intrinsic_value, price.close_price)

    return {
        "as_of_date": price.price_date,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "price_to_fcf": price_to_fcf,
        "ev_to_ebit": ev_to_ebit,
        "roe": roe,
        "roic": roic,
        "debt_to_equity": debt_to_equity,
        "current_ratio": None,  # not derivable: schema has no current assets/liabilities split
        "uncapped_dividend_yield": yields.uncapped_dividend_yield,
        "grossed_up_dividend_yield": yields.grossed_up_dividend_yield,
        "payout_ratio": payout_ratio,
        "dcf_intrinsic_value": dcf_intrinsic_value,
        "graham_number": graham,
        "margin_of_safety_percent": margin_of_safety,
        "valuation_method": valuation_method,
    }


# (precision, scale) for every valuation_metrics NUMERIC column, mirroring
# db/schema.sql exactly. Used as a final, purely mechanical safety net
# immediately before upsert - added 2026-10-02 after BRN (roic = 10,129.90%,
# overflowing NUMERIC(6,2)'s 9999.99 limit) and WHI (pb_ratio = ~203 million,
# overflowing NUMERIC(10,2)'s ~100 million limit; roe = 134,600%, also over
# NUMERIC(6,2)'s limit) both crashed individually despite the
# margin_of_safety_percent and payout_ratio guards already in place.
# Those two guards use a tighter, business-meaningful sanity threshold
# (5000%) and stay as-is; this is a broader backstop covering every field,
# since the same failure mode turned out not to be isolated to the two
# fields hit first - it recurs on any ratio, given enough companies
# (pre-revenue, distressed, or negative-equity companies in a large
# universe routinely produce mathematically correct but absurd ratios).
_COLUMN_PRECISION = {
    "pe_ratio": (10, 2), "pb_ratio": (10, 2), "price_to_fcf": (10, 2),
    "ev_to_ebit": (10, 2), "roe": (6, 2), "roic": (6, 2),
    "debt_to_equity": (10, 2), "current_ratio": (6, 2),
    "uncapped_dividend_yield": (6, 2), "grossed_up_dividend_yield": (6, 2),
    "payout_ratio": (6, 2), "dcf_intrinsic_value": (12, 4),
    "graham_number": (12, 4), "margin_of_safety_percent": (6, 2),
}


def _clamp_to_column_precision(metrics: dict) -> dict:
    """Null out (not crash on) any value that would overflow its target
    NUMERIC column, so one pathological field never costs an entire
    company its valuation row."""
    clamped = dict(metrics)
    for key, (precision, scale) in _COLUMN_PRECISION.items():
        value = clamped.get(key)
        if value is None:
            continue
        limit = Decimal(10) ** (precision - scale)
        if abs(value) >= limit:
            logger.warning(
                "%s=%s would overflow NUMERIC(%d,%d) - storing NULL instead of crashing the upsert",
                key, value, precision, scale,
            )
            clamped[key] = None
    return clamped


def upsert_valuation_metric(session: Session, company_id, metrics: dict) -> dict:
    """Upserts the row and returns the metrics actually written (i.e.
    post-clamp) - callers that log or return these values should use the
    return value, not their own pre-clamp dict, so console output and the
    database never disagree about what was stored."""
    metrics = _clamp_to_column_precision(metrics)
    stmt = insert(ValuationMetric).values(company_id=company_id, **metrics)
    update_cols = {k: getattr(stmt.excluded, k) for k in metrics}
    stmt = stmt.on_conflict_do_update(
        index_elements=[ValuationMetric.company_id, ValuationMetric.as_of_date],
        set_=update_cols,
    )
    session.execute(stmt)
    return metrics


def run_valuation_for_company(
    session: Session,
    company: Company,
    *,
    fcf_average_years: int = DEFAULT_FCF_AVERAGE_YEARS,
    **dcf_kwargs,
) -> dict | None:
    inputs = gather_inputs(session, company, fcf_average_years=fcf_average_years)
    if inputs is None:
        return None
    metrics = compute_metrics(inputs, **dcf_kwargs)
    return upsert_valuation_metric(session, company.company_id, metrics)


def run_valuation(
    session: Session,
    asx_codes: list[str] | None = None,
    *,
    fcf_average_years: int = DEFAULT_FCF_AVERAGE_YEARS,
    **dcf_kwargs,
) -> dict[str, dict]:
    """Compute and upsert valuation metrics for the given ASX codes, or all
    active companies if none are given. Returns {asx_code: metrics}.

    Each company is isolated in its own try/except and committed
    individually (added 2026-10-02, after a single bad company's
    numeric overflow aborted a ~500-company run and lost every other
    company's work, since the whole batch previously shared one
    commit() at the end - see docs/AS_BUILT.md known-issue #12). A
    failure on one company is logged and the run continues with the
    rest, matching the pattern already used in price_ingestion.py and
    fundamentals_ingestion.py."""
    stmt = select(Company).where(Company.is_active.is_(True))
    if asx_codes:
        stmt = select(Company).where(Company.asx_code.in_(asx_codes))

    companies = list(session.execute(stmt).scalars())
    total = len(companies)
    results: dict[str, dict] = {}
    for i, company in enumerate(companies, start=1):
        try:
            metrics = run_valuation_for_company(session, company, fcf_average_years=fcf_average_years, **dcf_kwargs)
            session.commit()
            if metrics is not None:
                results[company.asx_code] = metrics
                logger.info("[%d/%d] Valued %s", i, total, company.asx_code)
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] Valuation failed for %s - skipping", i, total, company.asx_code)

    return results
