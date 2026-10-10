"""Is each rule beating the average by more than luck?
(docs/kb/features/statistics.md, docs/kb/decisions/adr-017-statistics-methods.md)

The track record already says how far each action's monthly calls beat or
trailed the average screened share. This adds the test: a t-test on the
calls' excess returns, from the permanent monthly summary (count, average
and sum of squares per month), so it covers the whole history.

Calls in one month and the next overlap when the horizon is longer than a
month (a 6-month return measured each month shares five months with the
next), which makes them look more certain than they are. The standard
error is widened by the square root of the horizon in months to allow for
that: a conservative rule of thumb, so Sift claims less, not more."""

from __future__ import annotations

import math

from scipy.stats import t as t_dist

from src.analytics.words import luck_odds

MIN_CALLS = 30
CONFIDENCE = 0.95            # the likely range holds 19 times in 20
BULLISH = ("BUY", "INVESTIGATE", "ACCUMULATE")
BEARISH = ("AVOID", "SELL")


def test(action: str, horizon_months: int, n: int, mean: float | None, sumsq: float | None) -> dict:
    """{kind, label, intended, low, high, p_value, luck, calls_needed}.

    kind: BEATING (the whole likely range above the average), TRAILING
    (wholly below), UNCLEAR (it spans the average), NEEDS_MORE (fewer than
    MIN_CALLS calls, or no spread recorded yet). intended: True when the
    result is what the action means (BUY beating, AVOID trailing), False for
    the opposite, None for neutral actions or no verdict."""
    base = {"low": None, "high": None, "p_value": None, "luck": None, "t": None}
    if n < MIN_CALLS or mean is None or sumsq is None:
        return base | {"kind": "NEEDS_MORE", "label": "Needs more calls", "intended": None,
                       "calls_needed": max(0, MIN_CALLS - n)}
    variance = max(0.0, (sumsq - n * mean * mean) / (n - 1))
    se = math.sqrt(variance / n) * math.sqrt(max(1, horizon_months))
    if se == 0:
        return base | {"kind": "NEEDS_MORE", "label": "Needs more calls", "intended": None, "calls_needed": 0}
    df = n - 1
    t = mean / se
    p = float(2 * (1 - t_dist.cdf(abs(t), df)))
    half = float(t_dist.ppf(0.5 + CONFIDENCE / 2, df)) * se
    low, high = mean - half, mean + half
    if low > 0:
        kind, label = "BEATING", "Beating the average"
    elif high < 0:
        kind, label = "TRAILING", "Trailing the average"
    else:
        kind, label = "UNCLEAR", "Too early to tell"
    intended = None
    if kind == "BEATING":
        intended = True if action in BULLISH else False if action in BEARISH else None
    elif kind == "TRAILING":
        intended = True if action in BEARISH else False if action in BULLISH else None
    return {"kind": kind, "label": label, "intended": intended, "low": low, "high": high, "t": t,
            "p_value": p, "luck": luck_odds(p), "calls_needed": 0}
