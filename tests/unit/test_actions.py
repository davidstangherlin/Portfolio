"""src/screening/actions.py - suggested action rules."""

from datetime import date
from decimal import Decimal

import pytest

from src.portfolio.holdings import PositionSummary
from src.screening.actions import suggest_action

TODAY = date(2026, 10, 2)


def _row(**overrides):
    """A company passing all four value tests with every marker clean."""
    row = {
        "mos_ok": "Y", "roe_ok": "Y", "de_ok": "Y", "yield_ok": "Y", "overall": "Y",
        "margin_of_safety_percent": Decimal("35"), "payout_ratio": Decimal("60"),
        "trap_risk": "N", "momentum_ok": "N", "fundamentals_trend": "STABLE",
        "earnings_quality": "STRONG", "cash_conversion": Decimal("110"),
        "dividend_trend": "STEADY", "price_signal": "UPTREND", "data_confidence": "HIGH",
    }
    row.update(overrides)
    return row


def _position(units="100", next_discount_date=None, pending="0"):
    return PositionSummary(asx_code="TST", units=Decimal(units), cost_base=Decimal("1000"),
                           next_discount_date=next_discount_date, units_pending_discount=Decimal(pending))


# --- not held ----------------------------------------------------------------

def test_clean_pass_is_buy():
    action, reason = suggest_action(_row())
    assert action == "BUY"
    assert "no red flags" in reason


def test_buy_mentions_momentum():
    assert "getting cheaper" in suggest_action(_row(momentum_ok="Y"))[1]


@pytest.mark.parametrize("flag,expected_text", [
    ({"payout_ratio": Decimal("520")}, "one-off dividend"),
    ({"earnings_quality": "WEAK", "cash_conversion": Decimal("45")}, "cash flow 45% of profit"),
    ({"dividend_trend": "CUT"}, "dividend cut"),
    ({"price_signal": "NEW LOWS"}, "new lows"),
    ({"data_confidence": "LOW"}, "low data confidence"),
    ({"trap_risk": "Y"}, "value-trap risk"),
])
def test_any_red_flag_downgrades_buy_to_investigate(flag, expected_text):
    action, reason = suggest_action(_row(**flag))
    assert action == "INVESTIGATE"
    assert expected_text in reason


def test_cheap_trap_with_weak_cash_is_avoid():
    action, _ = suggest_action(_row(trap_risk="Y", earnings_quality="WEAK", fundamentals_trend="DECLINING"))
    assert action == "AVOID"


def test_cheap_passing_three_of_four_is_investigate_naming_the_failed_test():
    action, reason = suggest_action(_row(de_ok="N", overall="N"))
    assert action == "INVESTIGATE"
    assert "fails debt/equity" in reason


def test_cheap_but_failing_two_is_watch():
    action, reason = suggest_action(_row(roe_ok="N", yield_ok="N", overall="N"))
    assert action == "WATCH"
    assert "ROE" in reason and "yield" in reason


def test_quality_company_not_yet_cheap_is_watch():
    action, reason = suggest_action(_row(mos_ok="N", overall="N", margin_of_safety_percent=Decimal("-12")))
    assert action == "WATCH"
    assert "wait for a better price" in reason


def test_watch_reason_still_carries_red_flags():
    # Found in end-to-end testing: a WATCH reading "ROE, debt and yield pass"
    # with no mention of weak cash conversion overstated the company's health.
    action, reason = suggest_action(_row(mos_ok="N", overall="N", margin_of_safety_percent=Decimal("-24"),
                                         earnings_quality="WEAK", cash_conversion=Decimal("45")))
    assert action == "WATCH"
    assert "weak earnings quality (cash flow 45% of profit)" in reason


def test_nothing_going_for_it_is_ignore():
    action, _ = suggest_action(_row(mos_ok="N", roe_ok="N", de_ok="N", yield_ok="N", overall="N"))
    assert action == "IGNORE"


# --- held --------------------------------------------------------------------

def test_held_clean_pass_is_hold_could_add():
    action, reason = suggest_action(_row(), _position(), TODAY)
    assert action == "HOLD"
    assert "could add" in reason


def test_held_declining_and_overvalued_is_sell():
    action, reason = suggest_action(
        _row(fundamentals_trend="DECLINING", margin_of_safety_percent=Decimal("-20"), mos_ok="N"), _position(), TODAY)
    assert action == "SELL"
    assert "trading above estimated value" in reason


def test_held_with_red_flag_is_review():
    action, reason = suggest_action(_row(dividend_trend="CUT"), _position(), TODAY)
    assert action == "REVIEW"
    assert "dividend cut" in reason


def test_held_well_above_value_is_review():
    action, reason = suggest_action(_row(mos_ok="N", margin_of_safety_percent=Decimal("-80")), _position(), TODAY)
    assert action == "REVIEW"
    assert "well above estimated value" in reason


def test_sell_flags_imminent_cgt_discount():
    position = _position(next_discount_date=date(2026, 10, 30), pending="40")
    _, reason = suggest_action(
        _row(fundamentals_trend="DECLINING", earnings_quality="WEAK"), position, TODAY)
    assert "40 units qualify for the CGT discount from 30 Oct 2026 (28 days)" in reason


def test_cgt_note_omitted_when_discount_is_months_away():
    position = _position(next_discount_date=date(2027, 6, 1), pending="40")
    _, reason = suggest_action(_row(fundamentals_trend="DECLINING", earnings_quality="WEAK"), position, TODAY)
    assert "CGT" not in reason


def test_hold_never_carries_the_cgt_note():
    position = _position(next_discount_date=date(2026, 10, 30), pending="40")
    _, reason = suggest_action(_row(), position, TODAY)
    assert "CGT" not in reason
