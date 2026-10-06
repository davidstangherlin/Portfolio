"""The settings registry (src/settings.py): live values, the modules that
read them, overrides, guard rails, and the score wheel's labels."""

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

import screen_asx
from src import settings as reg
from src.screening import actions, scores
from src.valuation import dcf, ddm, engine, markers

# The values every rule ran on before the registry existed. Changing a live
# value is a rules change (bump RULES_VERSION), so it should fail here first.
PINNED = {
    "dcf_growth_rate": D("0.08"), "ddm_growth_rate": D("0.05"), "discount_rate": D("0.09"),
    "terminal_growth_rate": D("0.025"), "stage1_years": 5, "fcf_average_years": 3,
    "min_margin_of_safety": D("20"), "min_roe": D("12"), "max_debt_equity": D("0.80"), "min_yield": D("4.5"),
    "earnings_quality_strong": D("100"), "earnings_quality_adequate": D("80"), "new_lows_range": D("10"),
    "dividend_cut_ratio": D("0.9"), "dividend_growth_ratio": D("1.05"), "roe_trend_points": D("2"),
    "revenue_trend_ratio": D("0.05"), "min_mos_trend": D("5"), "payout_warning": D("150"), "overvalued_review": D("-50"),
    "score_mos_strong": D("40"), "score_max_pe": D("15"), "score_max_pb": D("1.5"), "score_roe_high": D("20"),
    "score_min_roic": D("10"), "score_debt_equity_low": D("0.4"), "score_yield_high": D("6"),
    "score_max_payout": D("100"), "score_upper_range": D("50"),
}


def test_live_values_are_unchanged():
    assert {k: getattr(reg.LIVE, k) for k in PINNED} == PINNED


def test_every_setting_is_described_and_explained():
    kb = {e["id"] for e in json.loads((Path(__file__).resolve().parents[2] / "web/knowledge.json").read_text())["entries"]}
    assert {s.key for s in reg.SETTINGS} == set(PINNED)
    for s in reg.SETTINGS:
        assert s.group in dict(reg.GROUPS) and s.formula and s.used_in
        assert s.help_id in kb, s.key
        live = getattr(reg.LIVE, s.key)
        assert s.minimum <= live <= s.maximum, s.key


def test_modules_read_their_live_values_from_the_registry():
    L = reg.LIVE
    assert (dcf.DEFAULT_DISCOUNT_RATE, dcf.DEFAULT_GROWTH_RATE, dcf.DEFAULT_TERMINAL_GROWTH_RATE, dcf.DEFAULT_STAGE1_YEARS) == \
        (L.discount_rate, L.dcf_growth_rate, L.terminal_growth_rate, L.stage1_years)
    assert ddm.DEFAULT_GROWTH_RATE == L.ddm_growth_rate and engine.DEFAULT_FCF_AVERAGE_YEARS == L.fcf_average_years
    assert (markers.EARNINGS_QUALITY_STRONG, markers.NEW_LOWS_RANGE_THRESHOLD, markers.DIVIDEND_CUT_RATIO) == \
        (L.earnings_quality_strong, L.new_lows_range, L.dividend_cut_ratio)
    assert (screen_asx.DEFAULT_MIN_MARGIN_OF_SAFETY, screen_asx.DEFAULT_MIN_ROE, screen_asx.DEFAULT_MAX_DEBT_TO_EQUITY,
            screen_asx.DEFAULT_MIN_GROSSED_UP_YIELD, screen_asx.DEFAULT_MIN_MOS_TREND) == \
        (L.min_margin_of_safety, L.min_roe, L.max_debt_equity, L.min_yield, L.min_mos_trend)
    assert screen_asx.PAYOUT_RATIO_WARNING_THRESHOLD == actions.PAYOUT_WARNING_THRESHOLD == L.payout_warning


def test_overrides_use_the_consoles_units():
    s = reg.with_overrides({"discount_rate": "10", "stage1_years": "7", "min_roe": "15%", "max_debt_equity": "0.6", "min_yield": ""})
    assert (s.discount_rate, s.stage1_years, s.min_roe, s.max_debt_equity, s.min_yield) == (D("0.10"), 7, D("15"), D("0.6"), D("4.5"))
    assert reg.differences(s) == {"discount_rate": (D("0.09"), D("0.10")), "stage1_years": (5, 7),
                                  "min_roe": (D("12"), D("15")), "max_debt_equity": (D("0.80"), D("0.6"))}
    assert reg.to_display("discount_rate", s.discount_rate) == D("10.0")


@pytest.mark.parametrize("overrides, message", [
    ({"nonsense": "1"}, "Unknown setting"),
    ({"discount_rate": "abc"}, "must be a number"),
    ({"discount_rate": "40"}, "between 3 and 25"),
    ({"stage1_years": "5.5"}, "whole number"),
    ({"terminal_growth_rate": "5", "discount_rate": "4"}, "higher than the terminal growth"),
    ({"earnings_quality_adequate": "120"}, "STRONG must start at or above ADEQUATE"),
    ({"min_margin_of_safety": "45"}, "second margin-of-safety level"),
    ({"max_debt_equity": "0.3"}, "second debt-to-equity level"),
])
def test_guard_rails(overrides, message):
    with pytest.raises(reg.SettingsError, match=message):
        reg.with_overrides(overrides)


def test_score_wheel_labels_state_the_threshold_used():
    live = [c.label for checks in scores.score_card({}).values() for c in checks]
    assert "Margin of safety above 20%" in live and "Debt/equity below 0.8" in live and "In upper half of 52-week range" in live
    s = reg.with_overrides({"min_margin_of_safety": "30", "score_max_pe": "12", "score_upper_range": "60"})
    other = [c.label for checks in scores.score_card({}, None, s).values() for c in checks]
    assert {"Margin of safety above 30%", "P/E between 0 and 12", "Above 60% of 52-week range"} <= set(other)


def test_markers_follow_the_settings():
    assert markers.earnings_quality(D("90")) == "ADEQUATE"
    assert markers.earnings_quality(D("90"), strong=D("85"), adequate=D("60")) == "STRONG"
    assert markers.price_signal(D("-5"), D("15")) == "DOWNTREND"
    assert markers.price_signal(D("-5"), D("15"), new_lows=D("20")) == "NEW LOWS"
