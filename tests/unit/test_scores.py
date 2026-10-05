"""src/screening/scores.py - the company page's score wheel."""

from decimal import Decimal

from src.screening.scores import AXES, CHECKS_PER_AXIS, axis_scores, score_card
from tests.unit._builders import make_report


def _row(**overrides):
    """A company that should pass every one of the 30 checks."""
    row = {
        "margin_of_safety_percent": Decimal("45"), "pe_ratio": Decimal("9"), "pb_ratio": Decimal("1.1"),
        "current_price": Decimal("10"), "graham_number": Decimal("14"),
        "roe": Decimal("22"), "roic": Decimal("15"), "fundamentals_trend": "IMPROVING", "earnings_quality": "STRONG",
        "debt_to_equity": Decimal("0.2"), "grossed_up_dividend_yield": Decimal("7"), "payout_ratio": Decimal("60"),
        "dividend_trend": "GROWING", "price_signal": "UPTREND", "range_position_52w": Decimal("70"),
        "margin_of_safety_trend": Decimal("8"), "momentum_ok": "Y",
    }
    row.update(overrides)
    return row


def _healthy_report():
    return make_report(cash_and_equivalents=Decimal("200"), total_debt=Decimal("100"), total_equity=Decimal("700"),
                       free_cash_flow=Decimal("90"), net_profit_after_tax=Decimal("80"))


def test_every_axis_has_six_checks():
    card = score_card(_row(), _healthy_report())
    assert list(card) == list(AXES)
    assert all(len(checks) == CHECKS_PER_AXIS for checks in card.values())


def test_strong_company_scores_full_marks():
    assert axis_scores(score_card(_row(), _healthy_report())) == {axis: 6 for axis in AXES}


def test_missing_data_is_no_data_and_never_a_pass():
    card = score_card({}, None)
    assert all(check.passed is None for checks in card.values() for check in checks)
    assert axis_scores(card) == {axis: 0 for axis in AXES}


def test_negative_pe_is_not_cheap():
    value = {c.label: c.passed for c in score_card(_row(pe_ratio=Decimal("-4")), _healthy_report())["Value"]}
    assert value["P/E between 0 and 15"] is False


def test_net_debt_fails_the_cash_check():
    report = make_report(cash_and_equivalents=Decimal("50"), total_debt=Decimal("100"))
    health = {c.label: c.passed for c in score_card(_row(), report)["Health"]}
    assert health["More cash than debt"] is False


def test_non_payer_fails_dividend_checks_rather_than_reading_no_data():
    card = score_card(_row(grossed_up_dividend_yield=None, payout_ratio=None, dividend_trend="NONE"), _healthy_report())
    dividend = {c.label: c.passed for c in card["Dividend"]}
    assert dividend["Pays a dividend"] is False
    assert dividend["No standing dividend cut"] is False


def test_new_lows_fail_both_price_checks():
    momentum = {c.label: c.passed for c in score_card(_row(price_signal="NEW LOWS"), _healthy_report())["Momentum"]}
    assert momentum["Price above 200-day average"] is False
    assert momentum["Not making new 52-week lows"] is False


def test_momentum_checks_read_no_data_during_cold_start():
    card = score_card(_row(margin_of_safety_trend=None, momentum_ok="N"), _healthy_report())
    momentum = {c.label: c.passed for c in card["Momentum"]}
    assert momentum["Margin of safety improving (30 days)"] is None
    assert momentum["Margin of safety up 5+ points"] is None
