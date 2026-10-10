"""Short-selling caution (docs/kb/features/volume-and-short-selling.md).

Heavily shorted shares can still be bought, but they swing harder: bad news
lands on a crowded bet against the company, and good news can force short
sellers to buy back at once (a "short squeeze"). So short interest is a
caution shown beside the action, never a red flag that changes it.

The model uses the two measures professional short-interest services report
(ASIC's data as read by brokers and services such as ShortMan, S3 and
Ortex), plus the trend:

  short interest % = shares reported sold short / shares on issue
  days to cover    = shares reported sold short / average daily volume
                     (the 20 trading days up to the report): how many days
                     of normal trading short sellers would need to buy back
  change           = the move in short interest % over about a month

  HIGH      short interest at or above `short_warning` (10%), or at or above
            `short_caution` (5%) with days to cover at or above
            `days_to_cover_high` (10)
  ELEVATED  short interest at or above `short_caution` (5%), or at least
            SHORT_FLOOR (2%) with days to cover at or above
            `days_to_cover_caution` (5), or at least SHORT_FLOOR and up
            RISE_POINTS (2) or more over a month

Most ASX shares sit under 1% short; 5% puts a share among the most shorted
on the market and 10% at the very top. Days to cover only counts with a
meaningful short (SHORT_FLOOR), as a thinly traded share can show many days
to cover on a trivial position."""

from __future__ import annotations

from decimal import Decimal

from src.settings import LIVE, ModelSettings

SHORT_FLOOR = Decimal("2")   # % short below which days to cover and the trend don't count
RISE_POINTS = Decimal("2")   # a rise this large over a month is a caution on its own

LEVELS = ("HIGH", "ELEVATED")
ADVICE = {
    "HIGH": "expect sharp price swings; keep any position small",
    "ELEVATED": "expect bigger price swings than usual",
}


def level(short_percent, days_to_cover=None, change=None, settings: ModelSettings = LIVE) -> str | None:
    """'HIGH', 'ELEVATED' or None (no caution, or no ASIC report)."""
    if short_percent is None:
        return None
    s = Decimal(str(short_percent))
    days = Decimal(str(days_to_cover)) if days_to_cover is not None else None
    rise = Decimal(str(change)) if change is not None else None
    if s >= settings.short_warning or (s >= settings.short_caution and days is not None and days >= settings.days_to_cover_high):
        return "HIGH"
    if s >= settings.short_caution:
        return "ELEVATED"
    if s >= SHORT_FLOOR and ((days is not None and days >= settings.days_to_cover_caution) or (rise is not None and rise >= RISE_POINTS)):
        return "ELEVATED"
    return None


def caution(row: dict, settings: ModelSettings = LIVE) -> dict | None:
    """The caution for a screener row (short_percent, days_to_cover,
    short_change), in words, or None."""
    s, days, change = row.get("short_percent"), row.get("days_to_cover"), row.get("short_change")
    found = level(s, days, change, settings)
    if found is None:
        return None
    facts = [f"{Decimal(str(s)):.1f}% of shares sold short"]
    if days is not None:
        facts.append(f"{Decimal(str(days)):.1f} days to cover")
    if change is not None and Decimal(str(change)) >= RISE_POINTS:
        facts.append(f"up {Decimal(str(change)):.1f} points in a month")
    word = "heavily shorted" if found == "HIGH" else "shorted"
    return {"level": found, "advice": ADVICE[found], "text": f"{word} ({', '.join(facts)}): {ADVICE[found]}"}
