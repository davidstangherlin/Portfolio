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

Two trend fields support a "momentum into value" view and a value-trap
warning, both in docs/AS_BUILT.md §8.6: `margin_of_safety_trend` compares
today's margin_of_safety_percent against the most recent valuation_metrics
row at least `trend_days` old for the same company (NULL until that much
daily history exists - see scripts/daily_refresh.ps1); `fundamentals_trend`
classifies ROE/revenue direction across the same multi-year
`financial_reports` window used for the DCF/DDM average, independent of
price (NULL if fewer than 2 distinct FY reports are available).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Company, DailyPrice, FinancialReport, ValuationMetric
from src.settings import LIVE, ModelSettings
from src.valuation import dcf as dcf_module
from src.valuation import ddm as ddm_module
from src.valuation import markers
from src.valuation.dividends import dividend_yields
from src.valuation.graham import book_value_per_share, graham_number

logger = logging.getLogger(__name__)


DEFAULT_FCF_AVERAGE_YEARS = LIVE.fcf_average_years
DEFAULT_TREND_DAYS = 30

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
    reports: list[FinancialReport]  # the same fcf_average_years-year window, newest first - also used for fundamentals_trend
    shares_outstanding: Decimal | None
    dcf_free_cash_flow: Decimal | None  # mean FCF across the last fcf_average_years FY reports
    ddm_dividend_per_share: Decimal | None  # mean DPS across the same window, for sector-aware companies
    prior_margin_of_safety_percent: Decimal | None  # from the valuation_metrics row >= trend_days old, for margin_of_safety_trend
    history_reports: list[FinancialReport] = field(default_factory=list)  # up to DIVIDEND_HISTORY_YEARS FY reports, newest first
    recent_closes: list[Decimal] = field(default_factory=list)  # last 365 days of closes, newest first


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


_ROE_TREND_THRESHOLD = LIVE.roe_trend_points  # percentage points
_REVENUE_TREND_THRESHOLD = LIVE.revenue_trend_ratio  # 5%


def _roe(report: FinancialReport) -> Decimal | None:
    if report.net_profit_after_tax is not None and report.total_equity:
        return report.net_profit_after_tax / report.total_equity * 100
    return None


def _fundamentals_trend(reports: list[FinancialReport], roe_points: Decimal = _ROE_TREND_THRESHOLD,
                        revenue_ratio: Decimal = _REVENUE_TREND_THRESHOLD) -> str | None:
    """Classifies ROE/revenue direction across the latest vs oldest report
    in the fetched fcf_average_years window (`reports` is newest-first -
    see `_last_n_annual_reports`), independent of price. A simple,
    explainable heuristic - not a substitute for reading the actual
    numbers - intended to flag a potential value trap when combined with a
    passing margin_of_safety: cheap because the business is deteriorating,
    not because the market has mispriced it (see docs/AS_BUILT.md §8.6).
    Returns None if fewer than 2 distinct FY reports are available, or if
    neither ROE nor revenue is computable for both endpoints - there's
    nothing to compare."""
    if len(reports) < 2:
        return None
    latest, oldest = reports[0], reports[-1]

    roe_trend = None
    roe_latest, roe_oldest = _roe(latest), _roe(oldest)
    if roe_latest is not None and roe_oldest is not None:
        roe_trend = roe_latest - roe_oldest

    revenue_trend = None
    if latest.revenue is not None and oldest.revenue:
        revenue_trend = (latest.revenue - oldest.revenue) / oldest.revenue

    if roe_trend is None and revenue_trend is None:
        return None

    if (roe_trend is not None and roe_trend < -roe_points) or (
        revenue_trend is not None and revenue_trend < -revenue_ratio
    ):
        return "DECLINING"

    if (roe_trend is not None and roe_trend > roe_points) or (
        revenue_trend is not None and revenue_trend > revenue_ratio
    ):
        return "IMPROVING"

    return "STABLE"


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


def _prior_margin_of_safety(
    session: Session, company_id, as_of_date, trend_days: int
) -> Decimal | None:
    """The margin_of_safety_percent from the most recent valuation_metrics
    row at least `trend_days` old, used as the baseline for
    margin_of_safety_trend. Returns None if no row that old exists yet -
    expected during the cold-start period before daily automation
    (scripts/daily_refresh.ps1) has been running for `trend_days` days,
    not a bug."""
    cutoff = as_of_date - timedelta(days=trend_days)
    stmt = (
        select(ValuationMetric.margin_of_safety_percent)
        .where(ValuationMetric.company_id == company_id, ValuationMetric.as_of_date <= cutoff)
        .order_by(ValuationMetric.as_of_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _recent_closes(session: Session, company_id, as_of_date, days: int = 365) -> list[Decimal]:
    """Closing prices for the `days` calendar days up to and including
    `as_of_date`, newest first - the input to the price-position markers."""
    stmt = (
        select(DailyPrice.close_price)
        .where(
            DailyPrice.company_id == company_id,
            DailyPrice.price_date > as_of_date - timedelta(days=days),
            DailyPrice.price_date <= as_of_date,
        )
        .order_by(DailyPrice.price_date.desc())
    )
    return list(session.execute(stmt).scalars())


def gather_inputs(
    session: Session,
    company: Company,
    fcf_average_years: int = DEFAULT_FCF_AVERAGE_YEARS,
    trend_days: int = DEFAULT_TREND_DAYS,
) -> ValuationInputs | None:
    price = _latest_price(session, company.company_id)
    # One query serves both windows: the fcf_average_years slice for the
    # DCF/DDM base and fundamentals_trend, the longer history for dividend_trend.
    history_reports = _last_n_annual_reports(
        session, company.company_id, max(fcf_average_years, markers.DIVIDEND_HISTORY_YEARS)
    )
    reports = history_reports[:max(fcf_average_years, 1)]
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
    prior_margin_of_safety_percent = _prior_margin_of_safety(
        session, company.company_id, price.price_date, trend_days
    )
    return ValuationInputs(
        company=company,
        price=price,
        report=report,
        reports=reports,
        shares_outstanding=shares_outstanding,
        dcf_free_cash_flow=dcf_free_cash_flow,
        ddm_dividend_per_share=ddm_dividend_per_share,
        prior_margin_of_safety_percent=prior_margin_of_safety_percent,
        history_reports=history_reports,
        recent_closes=_recent_closes(session, company.company_id, price.price_date),
    )


def compute_metrics(
    inputs: ValuationInputs,
    *,
    growth_rate: Decimal | None = None,
    discount_rate: Decimal | None = None,
    terminal_growth_rate: Decimal | None = None,
    stage1_years: int | None = None,
    settings: ModelSettings = LIVE,
) -> dict:
    """Every valuation_metrics figure for one company. Assumptions and
    thresholds come from `settings` (the live registry unless the admin
    console's what-if lab passes another); an explicit growth, discount,
    terminal or stage-1 argument (run_valuation's CLI options) overrides it."""
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
        growth_rate = settings.ddm_growth_rate if sector_aware else settings.dcf_growth_rate
    discount_rate = settings.discount_rate if discount_rate is None else discount_rate
    terminal_growth_rate = settings.terminal_growth_rate if terminal_growth_rate is None else terminal_growth_rate
    stage1_years = settings.stage1_years if stage1_years is None else stage1_years

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

    # "Momentum into value" trend indicators (see module docstring and
    # docs/AS_BUILT.md §8.6). margin_of_safety_trend needs a prior
    # valuation_metrics snapshot (cold-start gap, not a bug, until daily
    # automation has accumulated trend_days of history); fundamentals_trend
    # only needs the financial_reports already fetched for the DCF/DDM
    # average, so it populates immediately.
    margin_of_safety_trend = None
    if margin_of_safety is not None and inputs.prior_margin_of_safety_percent is not None:
        margin_of_safety_trend = margin_of_safety - inputs.prior_margin_of_safety_percent

    fundamentals_trend = _fundamentals_trend(inputs.reports, settings.roe_trend_points, settings.revenue_trend_ratio)

    # Decision markers (src/valuation/markers.py). Cash conversion is
    # skipped for sector-aware companies: a bank's operating cash flow is
    # dominated by loan book movements and a REIT's profit by property
    # revaluations, so OCF/NPAT says nothing about earnings quality there.
    cash_conversion = None if sector_aware else markers.cash_conversion_percent(inputs.reports)
    history = inputs.history_reports or inputs.reports

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
        "margin_of_safety_trend": margin_of_safety_trend,
        "fundamentals_trend": fundamentals_trend,
        "cash_conversion": cash_conversion,
        "earnings_quality": markers.earnings_quality(cash_conversion, settings.earnings_quality_strong,
                                                     settings.earnings_quality_adequate),
        "price_vs_200d": markers.price_vs_moving_average(inputs.recent_closes),
        "range_position_52w": markers.range_position(inputs.recent_closes),
        "dividend_trend": markers.dividend_trend(history, settings.dividend_cut_ratio, settings.dividend_growth_ratio),
        "data_confidence": markers.data_confidence(price, report, len(history), len(inputs.recent_closes)),
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
    "margin_of_safety_trend": (6, 2),
    "cash_conversion": (10, 2), "price_vs_200d": (10, 2), "range_position_52w": (6, 2),
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
    trend_days: int = DEFAULT_TREND_DAYS,
    **dcf_kwargs,
) -> dict | None:
    inputs = gather_inputs(session, company, fcf_average_years=fcf_average_years, trend_days=trend_days)
    if inputs is None:
        return None
    metrics = compute_metrics(inputs, **dcf_kwargs)
    return upsert_valuation_metric(session, company.company_id, metrics)


def run_valuation(
    session: Session,
    asx_codes: list[str] | None = None,
    *,
    fcf_average_years: int = DEFAULT_FCF_AVERAGE_YEARS,
    trend_days: int = DEFAULT_TREND_DAYS,
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
            metrics = run_valuation_for_company(
                session, company, fcf_average_years=fcf_average_years, trend_days=trend_days, **dcf_kwargs
            )
            session.commit()
            if metrics is not None:
                results[company.asx_code] = metrics
                logger.info("[%d/%d] Valued %s", i, total, company.asx_code)
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] Valuation failed for %s - skipping", i, total, company.asx_code)

    return results
