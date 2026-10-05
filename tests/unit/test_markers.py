"""src/valuation/markers.py - the four decision markers."""

from decimal import Decimal

import pytest

from src.valuation import markers

from _builders import make_price, make_report


# --- earnings quality --------------------------------------------------------

def test_cash_conversion_sums_across_years():
    reports = [
        make_report(operating_cash_flow=Decimal("90"), net_profit_after_tax=Decimal("100")),
        make_report(operating_cash_flow=Decimal("150"), net_profit_after_tax=Decimal("100")),
    ]
    assert markers.cash_conversion_percent(reports) == Decimal("120")


def test_cash_conversion_none_for_loss_maker():
    reports = [make_report(operating_cash_flow=Decimal("50"), net_profit_after_tax=Decimal("-10"))]
    assert markers.cash_conversion_percent(reports) is None


def test_cash_conversion_ignores_years_missing_either_figure():
    reports = [
        make_report(operating_cash_flow=Decimal("80"), net_profit_after_tax=Decimal("100")),
        make_report(operating_cash_flow=None, net_profit_after_tax=Decimal("100")),
    ]
    assert markers.cash_conversion_percent(reports) == Decimal("80")


@pytest.mark.parametrize("conversion,expected", [
    (Decimal("130"), "STRONG"), (Decimal("100"), "STRONG"), (Decimal("85"), "ADEQUATE"),
    (Decimal("79.99"), "WEAK"), (Decimal("-20"), "WEAK"), (None, None),
])
def test_earnings_quality_bands(conversion, expected):
    assert markers.earnings_quality(conversion) == expected


# --- price position ----------------------------------------------------------

def test_price_vs_moving_average():
    closes = [Decimal("12")] + [Decimal("10")] * 199  # newest first
    # average of the 200 = (12 + 199*10) / 200 = 10.01
    assert markers.price_vs_moving_average(closes) == pytest.approx(Decimal("19.88"), abs=Decimal("0.01"))


def test_price_vs_moving_average_needs_200_days():
    assert markers.price_vs_moving_average([Decimal("10")] * 199) is None


def test_range_position():
    closes = [Decimal("15")] + [Decimal("10"), Decimal("20")] * 60
    assert markers.range_position(closes) == Decimal("50")


def test_range_position_needs_enough_history():
    assert markers.range_position([Decimal("10"), Decimal("20")] * 40) is None


@pytest.mark.parametrize("vs_200d,range_pos,expected", [
    (Decimal("-12"), Decimal("4"), "NEW LOWS"),
    (Decimal("-12"), Decimal("40"), "DOWNTREND"),
    (Decimal("-12"), None, "DOWNTREND"),
    (Decimal("3"), Decimal("2"), "UPTREND"),
    (None, Decimal("50"), None),
])
def test_price_signal(vs_200d, range_pos, expected):
    assert markers.price_signal(vs_200d, range_pos) == expected


# --- dividend reliability ----------------------------------------------------

def _dividend_history(*oldest_to_newest):
    # markers expect newest first, like _last_n_annual_reports returns
    return [make_report(fiscal_year=2020 + i, dividends_per_share=d) for i, d in enumerate(oldest_to_newest)][::-1]


@pytest.mark.parametrize("history,expected", [
    ((Decimal("1.00"), Decimal("1.05"), Decimal("1.12")), "GROWING"),
    ((Decimal("1.00"), Decimal("1.00"), Decimal("1.02")), "STEADY"),
    ((Decimal("1.00"), Decimal("0.80"), Decimal("1.20")), "GROWING"),  # cut since restored no longer counts
    ((Decimal("1.00"), Decimal("1.00"), Decimal("0.80")), "CUT"),  # fresh cut
    ((Decimal("1.00"), Decimal("1.00"), Decimal("0.60"), Decimal("0.62"), Decimal("0.63")), "CUT"),  # old cut, never restored
    ((Decimal("1.00"), Decimal("0.70"), Decimal("0.95"), Decimal("0.96"), Decimal("0.95")), "STEADY"),  # dipped, back near the norm
    ((Decimal("1.00"), Decimal("0")), "CUT"),  # suspended
    ((Decimal("0"), Decimal("0"), Decimal("0")), "NONE"),
    ((Decimal("1.00"),), None),  # one year can't show a trend
])
def test_dividend_trend(history, expected):
    assert markers.dividend_trend(_dividend_history(*history)) == expected


def test_dividend_trend_after_special_dividend_reads_as_cut():
    # TWR's shape (docs/AS_BUILT.md §8.1): normal, special, back to normal
    assert markers.dividend_trend(_dividend_history(Decimal("0.10"), Decimal("1.19"), Decimal("0.12"))) == "CUT"


def test_dividend_trend_one_special_year_does_not_set_the_baseline():
    # The median of the earlier years ignores a single special: two years
    # on from it, a dividend back at its normal level reads as steady.
    history = _dividend_history(Decimal("0.10"), Decimal("1.19"), Decimal("0.10"), Decimal("0.10"))
    assert markers.dividend_trend(history) == "STEADY"


def test_variable_payout_miner_flags_only_while_the_dividend_is_down():
    # BHP-style: a peak year, then a lower but stable payout. Below the
    # earlier median it's a standing cut; restored to the norm it isn't.
    assert markers.dividend_trend(_dividend_history(
        Decimal("2.00"), Decimal("3.25"), Decimal("1.70"), Decimal("1.46"), Decimal("1.40"))) == "CUT"
    assert markers.dividend_trend(_dividend_history(
        Decimal("2.00"), Decimal("3.25"), Decimal("1.70"), Decimal("1.46"), Decimal("1.90"))) == "STEADY"


# --- data confidence ---------------------------------------------------------

def test_data_confidence_high_with_everything_present():
    assert markers.data_confidence(make_price(), make_report(), report_count=4, price_history_count=250) == "HIGH"


def test_data_confidence_short_price_history_alone_still_high():
    # 10 of 11 checks - e.g. a database only ever fed 1 month of prices
    assert markers.data_confidence(make_price(), make_report(), report_count=4, price_history_count=20) == "HIGH"


def test_data_confidence_low_when_statements_sparse():
    report = make_report(eps=None, net_profit_after_tax=None, revenue=None, total_debt=None,
                         operating_cash_flow=None, free_cash_flow=None)
    assert markers.data_confidence(make_price(), report, report_count=1, price_history_count=20) == "LOW"
