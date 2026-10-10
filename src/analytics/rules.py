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
that: a conservative rule of thumb, so Sift claims less, not more.

Many tests at once (every action at every period) means some pass by
chance. `adjust()` applies the Benjamini-Hochberg procedure (1995) across
them all: a test only counts as a finding if it survives with at most 5%
false findings expected, its luck odds are the adjusted ones, and every
bar is widened to the matching level (Benjamini and Yekutieli, 2005), so a
bar clear of the average always means a finding and vice versa."""

from __future__ import annotations

import math

from scipy.stats import t as t_dist

from src.analytics.words import luck_odds
from src.settings import LIVE

MIN_CALLS = LIVE.stats_min_calls   # an admin setting (Admin, Model and rules, Statistics)
CONFIDENCE = 0.95            # the likely range holds 19 times in 20
BULLISH = ("BUY", "INVESTIGATE", "ACCUMULATE")
BEARISH = ("AVOID", "SELL")


def test(action: str, horizon_months: int, n: int, mean: float | None, sumsq: float | None,
         min_calls: int | None = None) -> dict:
    """{kind, label, intended, low, high, p_value, luck, calls_needed}.

    kind: BEATING (the whole likely range above the average), TRAILING
    (wholly below), UNCLEAR (it spans the average), NEEDS_MORE (fewer than
    MIN_CALLS calls, or no spread recorded yet). intended: True when the
    result is what the action means (BUY beating, AVOID trailing), False for
    the opposite, None for neutral actions or no verdict."""
    min_calls = min_calls or MIN_CALLS
    base = {"low": None, "high": None, "p_value": None, "luck": None, "t": None, "min_calls": min_calls}
    if n < min_calls or mean is None or sumsq is None:
        return base | {"kind": "NEEDS_MORE", "label": "Needs more calls", "intended": None,
                       "calls_needed": max(0, min_calls - n)}
    variance = max(0.0, (sumsq - n * mean * mean) / (n - 1))
    se = math.sqrt(variance / n) * math.sqrt(max(1, horizon_months))
    if se == 0:
        return base | {"kind": "NEEDS_MORE", "label": "Needs more calls", "intended": None, "calls_needed": 0}
    df = n - 1
    t = mean / se
    p = float(2 * (1 - t_dist.cdf(abs(t), df)))
    return _judge(action, mean, se, df, t, p, 1 - CONFIDENCE, min_calls) | {"_action": action}


FALSE_FINDINGS = 0.05   # Benjamini-Hochberg: at most 5% of findings expected to be false


def _judge(action, mean, se, df, t, p, alpha, min_calls, q=None) -> dict:
    half = float(t_dist.ppf(1 - alpha / 2, df)) * se
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
            "p_value": p, "q_value": q, "luck": luck_odds(q if q is not None else p), "calls_needed": 0,
            "min_calls": min_calls, "mean": mean, "se": se, "df": df, "level": 1 - alpha}


def adjust(tests: list[dict]) -> int:
    """Benjamini-Hochberg across a family of tests, in place. Returns the
    number of tests in the family (those with a p-value)."""
    family = [x for x in tests if x.get("p_value") is not None]
    m = len(family)
    if not m:
        return 0
    ranked = sorted(family, key=lambda x: x["p_value"])
    found = max((k for k, x in enumerate(ranked, start=1) if x["p_value"] <= k * FALSE_FINDINGS / m), default=0)
    q, running = [0.0] * m, 1.0
    for i in range(m - 1, -1, -1):  # adjusted p-values: the smallest m x p / rank from here up
        running = min(running, ranked[i]["p_value"] * m / (i + 1))
        q[i] = running
    alpha = max(found, 1) * FALSE_FINDINGS / m
    for x, qv in zip(ranked, q):
        action = x.pop("_action")
        x.update(_judge(action, x["mean"], x["se"], x["df"], x["t"], x["p_value"], alpha, x["min_calls"], qv) | {"family": m})
    return m
