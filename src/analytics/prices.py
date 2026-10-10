"""Each security's price behaviour, worked out nightly into
`price_statistics` (docs/kb/features/statistics.md).

- Volatility: how much the price usually moves in a year, the standard
  deviation of daily log returns over up to three years, times sqrt(252).
- Beta: how much it moves with the market, the slope of its weekly returns
  on an ASX 200 fund's (IOZ, else STW, A200 or VAS) over up to three years.
  Weekly, because many small companies don't trade every day. Kept for the
  crash test simulator to come.
- Likely range: where the price would end in a typical year, two years in
  three: price x e^(-volatility) to price x e^(+volatility).
- Chance of reaching a level within 12 months: how often a price moving
  like this one touches the level at least once in a year, assuming no
  trend (a driftless random walk in the log price): 2 x (1 - N(ln(level /
  price) / volatility)). A level at or below today's price is already
  reached, so it has no chance figure.

These describe how the price moves; they know nothing about news, results
or whether the share is cheap, and the pages say so."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import statsmodels.api as sm
from scipy.stats import norm
from sqlalchemy import text

from src.analytics.words import chance_words
from src.settings import LIVE

logger = logging.getLogger(__name__)

YEARS = LIVE.stats_years     # price history used (an admin setting: Admin, Model and rules, Statistics)
TRADING_DAYS = 252
MIN_DAILY_RETURNS = 250      # about a year: fewer and there's no volatility
MIN_WEEKLY_RETURNS = 52      # a year of weeks for beta
MARKET_CODES = ("IOZ", "STW", "A200", "VAS")  # ASX 200 funds first; VAS (ASX 300) as a last resort


@dataclass
class PriceStats:
    as_of_date: date
    price: float
    observations: int
    volatility: float | None      # a fraction: 0.32 is 32% a year
    beta: float | None


def volatility(closes: np.ndarray) -> float | None:
    if len(closes) - 1 < MIN_DAILY_RETURNS:
        return None
    returns = np.diff(np.log(closes))
    return float(np.std(returns, ddof=1) * math.sqrt(TRADING_DAYS))


def weekly(dates: list[date], closes: np.ndarray) -> dict[date, float]:
    """The last close of each week, keyed by the week's Monday."""
    out: dict[date, float] = {}
    for d, c in zip(dates, closes):
        out[d - timedelta(days=d.weekday())] = float(c)
    return out


def beta(share: dict[date, float], market: dict[date, float]) -> float | None:
    weeks = sorted(set(share) & set(market))
    if len(weeks) - 1 < MIN_WEEKLY_RETURNS:
        return None
    s = np.diff(np.log([share[w] for w in weeks]))
    m = np.diff(np.log([market[w] for w in weeks]))
    if np.var(m) == 0:
        return None
    fit = sm.OLS(s, sm.add_constant(m)).fit()
    return float(fit.params[1])


def likely_range(price: float, vol: float | None, years: float = 1.0) -> tuple[float, float] | None:
    """Two years in three (one standard deviation either side, in log price)."""
    if vol is None:
        return None
    spread = vol * math.sqrt(years)
    return price * math.exp(-spread), price * math.exp(spread)


def chance_of_reaching(price: float, level: float | None, vol: float | None, years: float = 1.0) -> float | None:
    """The chance a price moving like this touches `level` at least once
    within `years`. None when the level is already reached or unknown."""
    if level is None or vol is None or vol <= 0 or level <= price:
        return None
    distance = math.log(level / price) / (vol * math.sqrt(years))
    return float(min(1.0, 2 * (1 - norm.cdf(distance))))


def _closes(session, company_id, since: date) -> tuple[list[date], np.ndarray]:
    rows = session.execute(text("""
        SELECT price_date, close_price FROM daily_prices
        WHERE company_id = :c AND price_date >= :s AND close_price > 0 ORDER BY price_date"""),
        {"c": company_id, "s": since}).all()
    return [r[0] for r in rows], np.array([float(r[1]) for r in rows])


def market_weekly(session, today: date) -> tuple[str | None, dict[date, float]]:
    since = today - timedelta(days=365 * YEARS + 7)
    for code in MARKET_CODES:
        cid = session.execute(text("SELECT company_id FROM companies WHERE asx_code = :c"), {"c": code}).scalar()
        if cid is None:
            continue
        dates, closes = _closes(session, cid, since)
        if len(dates) > MIN_DAILY_RETURNS:
            return code, weekly(dates, closes)
    return None, {}


def compute(session, company_id, since: date, market: dict[date, float]) -> PriceStats | None:
    dates, closes = _closes(session, company_id, since)
    if len(dates) < 2:
        return None
    return PriceStats(dates[-1], float(closes[-1]), len(dates) - 1, volatility(closes),
                      beta(weekly(dates, closes), market) if market else None)


def refresh(session, today: date) -> dict:
    """Recompute every active security's figures. Returns counts for the log."""
    since = today - timedelta(days=365 * YEARS + 7)
    market_code, market = market_weekly(session, today)
    if not market:
        logger.warning("No ASX 200 fund prices (%s): beta left blank", ", ".join(MARKET_CODES))
    companies = session.execute(text("""
        SELECT c.company_id, c.security_type,
               (SELECT v.dcf_intrinsic_value FROM valuation_metrics v WHERE v.company_id = c.company_id
                ORDER BY v.as_of_date DESC LIMIT 1) AS estimated_value,
               (SELECT i.target_mean FROM company_insights i WHERE i.company_id = c.company_id) AS target
        FROM companies c WHERE c.is_active""")).mappings().all()
    done = with_vol = 0
    for c in companies:
        stats = compute(session, c["company_id"], since, market)
        if stats is None:
            continue
        rng = likely_range(stats.price, stats.volatility)
        value = float(c["estimated_value"]) if c["estimated_value"] is not None and c["security_type"] == "SHARE" else None
        target = float(c["target"]) if c["target"] is not None and c["security_type"] == "SHARE" else None
        session.execute(text("""
            INSERT INTO price_statistics (company_id, as_of_date, price, observations, volatility, beta, market_code,
                range_low, range_high, value_level, chance_value, target_level, chance_target, computed_at)
            VALUES (:c, :d, :p, :n, :vol, :beta, :mkt, :lo, :hi, :vl, :cv, :tl, :ct, now())
            ON CONFLICT (company_id) DO UPDATE SET as_of_date = EXCLUDED.as_of_date, price = EXCLUDED.price,
                observations = EXCLUDED.observations, volatility = EXCLUDED.volatility, beta = EXCLUDED.beta,
                market_code = EXCLUDED.market_code, range_low = EXCLUDED.range_low, range_high = EXCLUDED.range_high,
                value_level = EXCLUDED.value_level, chance_value = EXCLUDED.chance_value,
                target_level = EXCLUDED.target_level, chance_target = EXCLUDED.chance_target, computed_at = now()"""),
            {"c": c["company_id"], "d": stats.as_of_date, "p": stats.price, "n": stats.observations,
             "vol": stats.volatility, "beta": stats.beta, "mkt": market_code if stats.beta is not None else None,
             "lo": rng and rng[0], "hi": rng and rng[1], "vl": value,
             "cv": chance_of_reaching(stats.price, value, stats.volatility),
             "tl": target, "ct": chance_of_reaching(stats.price, target, stats.volatility)})
        done += 1
        with_vol += stats.volatility is not None
    return {"securities": done, "with_volatility": with_vol, "market": market_code}


def _f(v) -> float | None:
    return float(v) if v is not None else None


def company_statistics(session, company_id) -> dict | None:
    """The company page's figures in plain words, or None before the first
    nightly run. Chances come with their words ("Possible", "about 4 in 10")."""
    r = session.execute(text("SELECT * FROM price_statistics WHERE company_id = :c"), {"c": company_id}).mappings().first()
    if r is None:
        return None
    price, vol = _f(r["price"]), _f(r["volatility"])

    def chance(kind, label, level, probability):
        if level is None:
            return None
        level = float(level)
        return {"kind": kind, "label": label, "level": level, "above_today_percent": (level / price - 1) * 100,
                "already_reached": level <= price, "chance": _f(probability), "words": chance_words(_f(probability))}

    chances = [x for x in (chance("value", "Sift's estimated value", r["value_level"], r["chance_value"]),
                           chance("target", "Analysts' target", r["target_level"], r["chance_target"])) if x]
    return {"as_of_date": r["as_of_date"], "price": price, "volatility_percent": vol * 100 if vol is not None else None,
            "beta": _f(r["beta"]), "market_code": r["market_code"], "observations": r["observations"],
            "years_of_prices": round(r["observations"] / TRADING_DAYS, 1),
            "range_low": _f(r["range_low"]), "range_high": _f(r["range_high"]), "chances": chances}


__all__ = ["refresh", "company_statistics", "volatility", "beta", "likely_range", "chance_of_reaching"]
