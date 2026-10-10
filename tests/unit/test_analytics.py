"""The statistics' maths against known answers (src/analytics/,
docs/kb/features/statistics.md)."""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from src.analytics import prices, rules, words


@pytest.mark.parametrize("p, in_ten, word, text", [
    (0.02, 0, "Very unlikely", "less than 1 in 10"),
    (0.17, 2, "Unlikely", "about 2 in 10"),
    (0.38, 4, "Possible", "about 4 in 10"),
    (0.5, 5, "About even", "about 5 in 10"),
    (0.63, 6, "Likely", "about 6 in 10"),
    (0.84, 8, "Very likely", "about 8 in 10"),
    (0.97, 10, "Very likely", "more than 9 in 10"),
])
def test_chances_in_words(p, in_ten, word, text):
    assert words.chance_words(p) == {"in_ten": in_ten, "word": word, "text": text}
    assert words.chance_words(None) is None


def test_luck_as_odds():
    assert words.luck_odds(0.025) == "about a 1 in 40 chance"
    assert words.luck_odds(0.0004) == "less than a 1 in 1,000 chance"
    assert words.luck_odds(0.7) == "better than an even chance"


def test_volatility_needs_a_year_and_scales_to_a_year():
    rng = np.random.default_rng(1)
    closes = 10 * np.exp(np.cumsum(rng.normal(0, 0.02, 600)))
    assert prices.volatility(closes[:200]) is None
    assert prices.volatility(closes) == pytest.approx(0.02 * math.sqrt(252), rel=0.08)


def test_beta_of_a_share_moving_twice_the_market():
    start, rng = date(2024, 1, 1), np.random.default_rng(2)
    days = [start + timedelta(days=i) for i in range(700) if (start + timedelta(days=i)).weekday() < 5]
    market = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
    share = 5 * (market / 100) ** 2   # log returns exactly twice the market's
    assert prices.beta(prices.weekly(days, share), prices.weekly(days, market)) == pytest.approx(2.0, abs=1e-6)
    assert prices.beta(prices.weekly(days[:100], share[:100]), prices.weekly(days[:100], market[:100])) is None  # under a year


def test_likely_range_and_chance_of_reaching():
    lo, hi = prices.likely_range(10.0, 0.3)
    assert (lo, hi) == pytest.approx((10 * math.exp(-0.3), 10 * math.exp(0.3)))
    # One standard deviation away: 2 x (1 - N(1)) = 0.317
    assert prices.chance_of_reaching(10.0, 10 * math.exp(0.3), 0.3) == pytest.approx(0.3173, abs=1e-4)
    assert prices.chance_of_reaching(10.0, 9.0, 0.3) is None      # already reached
    assert prices.chance_of_reaching(10.0, 12.0, None) is None    # no volatility yet
    assert prices.chance_of_reaching(10.0, 10.01, 0.3) == pytest.approx(1.0, abs=0.01)  # a step away: almost certain


def test_rule_test_verdicts():
    def sumsq(n, mean, sd):  # the sum of squares for n calls with this mean and spread
        return (n - 1) * sd * sd + n * mean * mean
    beating = rules.test("BUY", 1, 100, 3.0, sumsq(100, 3.0, 10.0))
    assert beating["kind"] == "BEATING" and beating["intended"] is True and beating["low"] > 0
    assert beating["p_value"] < 0.01 and beating["luck"] == f"about a 1 in {round(1 / beating['p_value']):,} chance"
    assert rules.test("AVOID", 1, 100, -3.0, sumsq(100, -3.0, 10.0))["intended"] is True   # AVOID should trail
    assert rules.test("BUY", 1, 100, -3.0, sumsq(100, -3.0, 10.0))["intended"] is False    # BUY trailing: the wrong way
    assert rules.test("WATCH", 1, 100, 3.0, sumsq(100, 3.0, 10.0))["intended"] is None     # neutral action
    unclear = rules.test("BUY", 1, 100, 1.0, sumsq(100, 1.0, 10.0))
    assert unclear["kind"] == "UNCLEAR" and unclear["low"] < 0 < unclear["high"]
    needs = rules.test("BUY", 1, 12, 5.0, sumsq(12, 5.0, 10.0))
    assert needs["kind"] == "NEEDS_MORE" and needs["calls_needed"] == 18
    assert rules.test("BUY", 1, 100, 3.0, None)["kind"] == "NEEDS_MORE"   # no spread recorded yet


def test_longer_horizons_widen_the_range_for_overlapping_calls():
    ss = 99 * 100 + 100 * 9
    one, six = rules.test("BUY", 1, 100, 3.0, ss), rules.test("BUY", 6, 100, 3.0, ss)
    assert (six["high"] - six["low"]) == pytest.approx((one["high"] - one["low"]) * math.sqrt(6))
    assert one["kind"] == "BEATING" and six["kind"] == "UNCLEAR"
