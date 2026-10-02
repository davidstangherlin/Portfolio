"""src/valuation/engine.py - pure functions and compute_metrics().

No database involved: compute_metrics() takes a ValuationInputs dataclass
and plain (unpersisted) ORM objects, so every test here runs in-memory.
Several cases regression-pin real figures from docs/AS_BUILT.md's change
log and known-issues table (SUN's FCF averaging, TWR's payout ratio,
BRN/WHI's numeric overflow), per the project's own "use the real company
figures already documented... as test fixtures" suggested next step.
"""

from decimal import Decimal

import pytest

from src.valuation import ddm as ddm_module
from src.valuation.engine import (
    _average_dividend_per_share,
    _average_free_cash_flow,
    _clamp_to_column_precision,
    _fundamentals_trend,
    _roe,
    compute_metrics,
)

from _builders import make_company, make_inputs, make_report


# --- _average_free_cash_flow / _average_dividend_per_share -----------------

def test_average_free_cash_flow_sun_three_year_regression():
    # Real case from docs/AS_BUILT.md §8.4/known-issue #9: SUN's FCF swung
    # $742M/$2,497M/$2,550M/$1,585M across FY2023-26 - a single-year DCF
    # base made margin of safety swing +34% to -10% depending only on
    # which year happened to be "latest". The 3-year average fix produced
    # $2,210.67M (of the last 3 years, FY2024-26) - pinned here exactly.
    reports = [
        make_report(fiscal_year=2026, free_cash_flow=Decimal("1585000000")),
        make_report(fiscal_year=2025, free_cash_flow=Decimal("2550000000")),
        make_report(fiscal_year=2024, free_cash_flow=Decimal("2497000000")),
    ]
    result = _average_free_cash_flow(reports)
    assert result == pytest.approx(Decimal("2210666666.67"), abs=Decimal("1"))


def test_average_free_cash_flow_none_when_no_values():
    reports = [make_report(free_cash_flow=None), make_report(free_cash_flow=None)]
    assert _average_free_cash_flow(reports) is None


def test_average_free_cash_flow_gracefully_handles_partial_gaps():
    # Only 2 of 3 reports have a usable FCF - mean of just those two, not
    # an error or a mean-including-zero.
    reports = [
        make_report(fiscal_year=2026, free_cash_flow=Decimal("100")),
        make_report(fiscal_year=2025, free_cash_flow=None),
        make_report(fiscal_year=2024, free_cash_flow=Decimal("200")),
    ]
    assert _average_free_cash_flow(reports) == Decimal("150")


def test_average_dividend_per_share_basic():
    reports = [make_report(dividends_per_share=Decimal("1.00")), make_report(dividends_per_share=Decimal("2.00"))]
    assert _average_dividend_per_share(reports) == Decimal("1.50")


# --- _fundamentals_trend -----------------------------------------------------

def test_fundamentals_trend_declining_roe_and_revenue():
    # newest-first, matching _last_n_annual_reports' ordering
    reports = [
        make_report(fiscal_year=2026, net_profit_after_tax=Decimal("10000000"), total_equity=Decimal("600000000"), revenue=Decimal("600000000")),
        make_report(fiscal_year=2025, net_profit_after_tax=Decimal("40000000"), total_equity=Decimal("600000000"), revenue=Decimal("700000000")),
        make_report(fiscal_year=2023, net_profit_after_tax=Decimal("120000000"), total_equity=Decimal("600000000"), revenue=Decimal("900000000")),
    ]
    assert _fundamentals_trend(reports) == "DECLINING"


def test_fundamentals_trend_improving_roe_and_revenue():
    reports = [
        make_report(fiscal_year=2026, net_profit_after_tax=Decimal("100000000"), total_equity=Decimal("500000000"), revenue=Decimal("550000000")),
        make_report(fiscal_year=2023, net_profit_after_tax=Decimal("10000000"), total_equity=Decimal("500000000"), revenue=Decimal("300000000")),
    ]
    assert _fundamentals_trend(reports) == "IMPROVING"


def test_fundamentals_trend_stable_when_within_thresholds():
    reports = [
        make_report(fiscal_year=2026, net_profit_after_tax=Decimal("121000000"), total_equity=Decimal("700000000"), revenue=Decimal("505000000")),
        make_report(fiscal_year=2023, net_profit_after_tax=Decimal("120000000"), total_equity=Decimal("700000000"), revenue=Decimal("500000000")),
    ]
    assert _fundamentals_trend(reports) == "STABLE"


def test_fundamentals_trend_none_with_fewer_than_two_reports():
    assert _fundamentals_trend([make_report()]) is None
    assert _fundamentals_trend([]) is None


def test_fundamentals_trend_none_when_neither_signal_computable():
    reports = [
        make_report(fiscal_year=2026, net_profit_after_tax=None, total_equity=None, revenue=None),
        make_report(fiscal_year=2023, net_profit_after_tax=None, total_equity=None, revenue=None),
    ]
    assert _fundamentals_trend(reports) is None


def test_roe_helper_basic_and_none_cases():
    assert _roe(make_report(net_profit_after_tax=Decimal("10"), total_equity=Decimal("100"))) == Decimal("10")
    assert _roe(make_report(net_profit_after_tax=None, total_equity=Decimal("100"))) is None
    assert _roe(make_report(net_profit_after_tax=Decimal("10"), total_equity=Decimal("0"))) is None


# --- _clamp_to_column_precision ----------------------------------------------

def test_clamp_to_column_precision_brn_whi_overflow_regression():
    # Real case from docs/AS_BUILT.md known-issue #15: BRN's roic hit
    # 10,129.90% (over NUMERIC(6,2)'s 9999.99 limit) and WHI's pb_ratio hit
    # ~203 million (over NUMERIC(10,2)'s ~100 million limit) with roe
    # simultaneously at 134,600% - both crashed run_valuation --all before
    # this guard existed. Every other field must survive untouched.
    metrics = {
        "roic": Decimal("10129.90"),
        "pe_ratio": Decimal("15.00"),
        "pb_ratio": Decimal("203000000.00"),
        "roe": Decimal("134600.00"),
        "debt_to_equity": Decimal("0.50"),
    }
    clamped = _clamp_to_column_precision(metrics)
    assert clamped["roic"] is None
    assert clamped["pb_ratio"] is None
    assert clamped["roe"] is None
    assert clamped["pe_ratio"] == Decimal("15.00")
    assert clamped["debt_to_equity"] == Decimal("0.50")


def test_clamp_to_column_precision_leaves_none_values_alone():
    clamped = _clamp_to_column_precision({"roic": None, "pe_ratio": Decimal("10.00")})
    assert clamped["roic"] is None
    assert clamped["pe_ratio"] == Decimal("10.00")


def test_clamp_to_column_precision_ignores_unknown_keys():
    # valuation_method/fundamentals_trend are text columns, not in
    # _COLUMN_PRECISION - must pass through completely untouched.
    clamped = _clamp_to_column_precision({"valuation_method": "DDM", "pe_ratio": Decimal("10.00")})
    assert clamped["valuation_method"] == "DDM"


# --- compute_metrics: DCF vs DDM sector routing -----------------------------

def test_compute_metrics_ordinary_sector_uses_dcf():
    inputs = make_inputs(
        company=make_company(sector="Basic Materials"),
        dcf_free_cash_flow=Decimal("110000000"),
    )
    metrics = compute_metrics(inputs)
    assert metrics["valuation_method"] == "DCF"
    assert metrics["dcf_intrinsic_value"] is not None


@pytest.mark.parametrize("sector", ["Financial Services", "Real Estate"])
def test_compute_metrics_sector_aware_sectors_use_ddm(sector):
    # Regression for known-issue #8: these sectors' FCF is routinely
    # negative (balance-sheet movements dominate it), so DCF is skipped
    # entirely and the DDM runs on dividends instead.
    inputs = make_inputs(
        company=make_company(sector=sector),
        dcf_free_cash_flow=Decimal("-3500000000"),  # negative - would skip DCF if this path were taken
        ddm_dividend_per_share=Decimal("2.0000"),
    )
    metrics = compute_metrics(inputs)
    assert metrics["valuation_method"] == "DDM"
    assert metrics["dcf_intrinsic_value"] is not None


def test_compute_metrics_sector_aware_but_no_dividend_gets_no_intrinsic_value():
    # A Financial Services company with no dividend history correctly gets
    # neither model's result - "skip rather than fabricate", same
    # philosophy as the ordinary DCF path's negative-FCF skip.
    inputs = make_inputs(
        company=make_company(sector="Financial Services"),
        dcf_free_cash_flow=Decimal("-3500000000"),
        ddm_dividend_per_share=None,
    )
    metrics = compute_metrics(inputs)
    assert metrics["valuation_method"] is None
    assert metrics["dcf_intrinsic_value"] is None


def test_compute_metrics_ordinary_sector_negative_fcf_skips_dcf():
    inputs = make_inputs(company=make_company(sector="Basic Materials"), dcf_free_cash_flow=Decimal("-100"))
    metrics = compute_metrics(inputs)
    assert metrics["valuation_method"] is None
    assert metrics["dcf_intrinsic_value"] is None


# --- compute_metrics: per-model growth_rate default (§8.6) ------------------

def test_compute_metrics_growth_rate_none_uses_ddm_default_for_sector_aware():
    inputs = make_inputs(
        company=make_company(sector="Financial Services"),
        dcf_free_cash_flow=Decimal("-3500000000"),
        ddm_dividend_per_share=Decimal("2.0000"),
    )
    metrics = compute_metrics(inputs)  # growth_rate=None
    expected = ddm_module.two_stage_ddm(Decimal("2.0000"), growth_rate=ddm_module.DEFAULT_GROWTH_RATE).intrinsic_value_per_share
    assert metrics["dcf_intrinsic_value"] == expected


def test_compute_metrics_explicit_growth_rate_overrides_uniformly():
    # An explicit --growth-rate still applies to whichever model runs,
    # same as before the per-model defaults were added.
    inputs = make_inputs(
        company=make_company(sector="Financial Services"),
        dcf_free_cash_flow=Decimal("-3500000000"),
        ddm_dividend_per_share=Decimal("2.0000"),
    )
    metrics = compute_metrics(inputs, growth_rate=Decimal("0.08"))
    expected = ddm_module.two_stage_ddm(Decimal("2.0000"), growth_rate=Decimal("0.08")).intrinsic_value_per_share
    assert metrics["dcf_intrinsic_value"] == expected


# --- compute_metrics: payout_ratio (§8.1, known-issue #14) ------------------

def test_compute_metrics_payout_ratio_twr_special_dividend_regression():
    # Real case: TWR's dividends_per_share ($1.1930) was 519% of that
    # year's eps ($0.2300) - a special dividend, not sustainable income.
    report = make_report(dividends_per_share=Decimal("1.1930"), eps=Decimal("0.2300"))
    metrics = compute_metrics(make_inputs(reports=[report]))
    assert metrics["payout_ratio"] == pytest.approx(Decimal("518.70"), abs=Decimal("0.01"))


def test_compute_metrics_payout_ratio_capped_when_implausible():
    # A near-zero EPS against a real dividend produces a mathematically
    # correct but absurd ratio - must be None, not a NUMERIC(6,2) overflow.
    report = make_report(dividends_per_share=Decimal("5.00"), eps=Decimal("0.0001"))
    metrics = compute_metrics(make_inputs(reports=[report]))
    assert metrics["payout_ratio"] is None


def test_compute_metrics_payout_ratio_none_when_no_dividend():
    report = make_report(dividends_per_share=None)
    metrics = compute_metrics(make_inputs(reports=[report]))
    assert metrics["payout_ratio"] is None


# --- compute_metrics: trend fields (§8.6) -----------------------------------

def test_compute_metrics_margin_of_safety_trend_computed_when_prior_exists():
    inputs = make_inputs(dcf_free_cash_flow=Decimal("110000000"), prior_margin_of_safety_percent=Decimal("30.00"))
    metrics = compute_metrics(inputs)
    assert metrics["margin_of_safety_percent"] is not None
    assert metrics["margin_of_safety_trend"] == metrics["margin_of_safety_percent"] - Decimal("30.00")


def test_compute_metrics_margin_of_safety_trend_none_cold_start():
    # No prior valuation_metrics snapshot - a genuine cold-start gap
    # (docs/AS_BUILT.md §8.6), not a bug.
    inputs = make_inputs(dcf_free_cash_flow=Decimal("110000000"), prior_margin_of_safety_percent=None)
    metrics = compute_metrics(inputs)
    assert metrics["margin_of_safety_trend"] is None


def test_compute_metrics_fundamentals_trend_surfaces_in_output():
    reports = [
        make_report(fiscal_year=2026, net_profit_after_tax=Decimal("10000000"), total_equity=Decimal("600000000"), revenue=Decimal("600000000")),
        make_report(fiscal_year=2023, net_profit_after_tax=Decimal("120000000"), total_equity=Decimal("600000000"), revenue=Decimal("900000000")),
    ]
    metrics = compute_metrics(make_inputs(reports=reports))
    assert metrics["fundamentals_trend"] == "DECLINING"


# --- compute_metrics: always-None current_ratio -----------------------------

def test_compute_metrics_current_ratio_always_none():
    # Deliberate: the schema has no current-assets/current-liabilities
    # split, so a genuine current ratio can't be derived (§8.4) - this
    # must never silently start returning a fabricated number.
    metrics = compute_metrics(make_inputs())
    assert metrics["current_ratio"] is None
