"""Reading Yahoo's analyst and holder data (docs/AS_BUILT.md §29), shaped
as yfinance 1.x returns it. No network."""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from src.ingestion.yahoo_client import parse_insights

TODAY = date(2026, 10, 6)
INFO = {"recommendationKey": "buy", "recommendationMean": 2.1, "numberOfAnalystOpinions": 12,
        "targetLowPrice": 5.2, "targetMeanPrice": 7.35, "targetMedianPrice": 7.4, "targetHighPrice": 9.0}
TREND = pd.DataFrame([
    {"period": "0m", "strongBuy": 3, "buy": 6, "hold": 2, "sell": 1, "strongSell": 0},
    {"period": "-1m", "strongBuy": 2, "buy": 6, "hold": 3, "sell": 1, "strongSell": 0},
    {"period": "-9m", "strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0},
    {"period": "-2m", "strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0},
])
MAJOR = pd.DataFrame({"Value": [0.0312, 0.4127, 0.4260, 312]},
                     index=["insidersPercentHeld", "institutionsPercentHeld", "institutionsFloatPercentHeld", "institutionsCount"])
FUNDS = pd.DataFrame([
    {"Date Reported": pd.Timestamp(datetime(2026, 6, 30)), "Holder": "Vanguard Total International Stock Index Fund",
     "pctHeld": 0.0123, "Shares": 9876543.0, "Value": 70000000, "pctChange": -0.015},
    {"Date Reported": pd.NaT, "Holder": "  ", "pctHeld": None, "Shares": None, "Value": None, "pctChange": None},
    {"Date Reported": pd.Timestamp(datetime(2026, 5, 31)), "Holder": "iShares Core MSCI EAFE ETF",
     "pctHeld": 0.0081, "Shares": 6500000.0, "Value": float("nan"), "pctChange": 0.2},
])


def test_ratings_targets_and_holders():
    ins = parse_insights(INFO, TREND, MAJOR, FUNDS, None, TODAY)
    assert (ins.recommendation_key, ins.recommendation_mean, ins.analyst_count) == ("buy", Decimal("2.1"), 12)
    assert (ins.target_low, ins.target_mean, ins.target_high) == (Decimal("5.2"), Decimal("7.35"), Decimal("9.0"))
    # Months counted back from today, oldest first; a month with no analysts is left out.
    assert [(r.rating_month, r.strong_buy, r.buy) for r in ins.ratings] == [
        (date(2026, 1, 1), 1, 0), (date(2026, 9, 1), 2, 6), (date(2026, 10, 1), 3, 6)]
    assert ins.insiders_percent == Decimal("3.1200") and ins.institutions_float_percent == Decimal("42.6000")
    assert ins.institutions_count == 312
    # A holder without a name is skipped and the ranks close up.
    [first, second] = ins.funds
    assert (first.rank, first.shares, first.percent_held, first.percent_change, first.date_reported) == (
        1, Decimal("9876543"), Decimal("1.2300"), Decimal("-1.5000"), date(2026, 6, 30))
    assert (second.rank, second.holder, second.value) == (2, "iShares Core MSCI EAFE ETF", None)
    assert ins.institutions == []


def test_a_small_company_with_nothing():
    ins = parse_insights({"recommendationKey": "none"}, pd.DataFrame(), pd.DataFrame(), None, None, TODAY)
    assert ins.recommendation_key is None and ins.target_mean is None
    assert ins.ratings == [] and ins.funds == [] and ins.insiders_percent is None


def test_major_holders_fall_back_to_the_profile():
    ins = parse_insights({"heldPercentInsiders": 0.5, "heldPercentInstitutions": 0.2}, None, None, None, None, TODAY)
    assert (ins.insiders_percent, ins.institutions_percent) == (Decimal("50.0000"), Decimal("20.0000"))
