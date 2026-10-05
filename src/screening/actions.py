"""Suggested action for each screened company (docs/AS_BUILT.md §9.1).

A transparent, rule-based next step plus the reason behind it, so the
output teaches the reasoning rather than just issuing a verdict. These are
research prompts, not financial advice.

Not held:  BUY / INVESTIGATE / WATCH / AVOID / IGNORE
Held:      SELL / REVIEW / ACCUMULATE / HOLD
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.portfolio.holdings import PositionSummary

PAYOUT_WARNING_THRESHOLD = Decimal("150")
OVERVALUED_MARGIN_OF_SAFETY = Decimal("-50")
CGT_TIMING_WINDOW_DAYS = 90

ACTION_ORDER = ("SELL", "REVIEW", "ACCUMULATE", "HOLD", "BUY", "INVESTIGATE", "WATCH", "AVOID", "IGNORE")
HELD_ACTIONS = ("SELL", "REVIEW", "ACCUMULATE", "HOLD")

_CORE_TESTS = (
    ("mos_ok", "margin of safety"),
    ("roe_ok", "ROE"),
    ("de_ok", "debt/equity"),
    ("yield_ok", "yield"),
)


def _fmt_units(units: Decimal) -> str:
    return f"{units.normalize():f}"


def red_flags(row: dict) -> list[str]:
    flags = []
    if row.get("trap_risk") == "Y":
        flags.append("value-trap risk (cheap but ROE/revenue declining)")
    payout = row.get("payout_ratio")
    if payout is not None and payout > PAYOUT_WARNING_THRESHOLD:
        flags.append(f"payout ratio {payout:.0f}% suggests a one-off dividend")
    if row.get("earnings_quality") == "WEAK":
        conversion = row.get("cash_conversion")
        detail = f" (cash flow {conversion:.0f}% of profit)" if conversion is not None else ""
        flags.append(f"weak earnings quality{detail}")
    if row.get("dividend_trend") == "CUT":
        flags.append("dividend cut and not yet restored")
    if row.get("price_signal") == "NEW LOWS":
        flags.append("price still making new lows")
    if row.get("data_confidence") == "LOW":
        flags.append("low data confidence, verify the inputs")
    return flags


def suggest_action(row: dict, position: PositionSummary | None = None, today: date | None = None) -> tuple[str, str]:
    passes = [label for key, label in _CORE_TESTS if row.get(key) == "Y"]
    fails = [label for key, label in _CORE_TESTS if row.get(key) != "Y"]
    flags = red_flags(row)
    if position is not None and position.units > 0:
        return _held_action(row, position, passes, fails, flags, today or date.today())
    return _not_held_action(row, passes, fails, flags)


def _not_held_action(row: dict, passes: list[str], fails: list[str], flags: list[str]) -> tuple[str, str]:
    cheap = row.get("mos_ok") == "Y"
    mos = row.get("margin_of_safety_percent")

    if row.get("trap_risk") == "Y" and row.get("earnings_quality") == "WEAK":
        return "AVOID", "looks cheap, but fundamentals are declining and profit isn't backed by cash"
    if len(passes) == 4:
        if flags:
            return "INVESTIGATE", "passes all four value tests, but check: " + "; ".join(flags)
        reason = "passes all four value tests with no red flags"
        if row.get("momentum_ok") == "Y":
            reason += ", and getting cheaper"
        return "BUY", reason
    if cheap and len(passes) == 3:
        reason = f"cheap and passes 3 of 4 tests (fails {fails[0]})"
        if flags:
            reason += "; check: " + "; ".join(flags)
        return "INVESTIGATE", reason
    if cheap:
        reason = f"cheap, but fails {', '.join(fails)}"
    elif row.get("momentum_ok") == "Y":
        reason = "getting cheaper quickly but not yet below estimated value"
    elif len(passes) == 3:
        price_note = f"margin of safety {mos:.0f}%" if mos is not None else "no intrinsic value estimate"
        reason = f"ROE, debt and yield pass but the price isn't cheap yet ({price_note}), wait for a better price"
    else:
        return "IGNORE", "no value signal"
    if flags:
        reason += "; check: " + "; ".join(flags)
    return "WATCH", reason


def _held_action(
    row: dict, position: PositionSummary, passes: list[str], fails: list[str], flags: list[str], today: date
) -> tuple[str, str]:
    mos = row.get("margin_of_safety_percent")

    sell_reasons = []
    if row.get("fundamentals_trend") == "DECLINING":
        if mos is not None and mos < 0:
            sell_reasons.append("trading above estimated value")
        if row.get("earnings_quality") == "WEAK":
            sell_reasons.append("profit not backed by cash")
        if row.get("dividend_trend") == "CUT":
            sell_reasons.append("dividend cut")

    if sell_reasons:
        action, reason = "SELL", "fundamentals declining and " + ", ".join(sell_reasons)
    else:
        review = list(flags)
        if mos is not None and mos < OVERVALUED_MARGIN_OF_SAFETY:
            review.append(f"now well above estimated value (margin of safety {mos:.0f}%)")
        if review:
            action, reason = "REVIEW", "; ".join(review)
        elif len(passes) == 4:
            # The same bar as BUY for a share you don't own: all four tests,
            # no red flags (any flag has already routed to REVIEW above).
            action, reason = "ACCUMULATE", "still passes all four value tests with no red flags, consider adding"
            if row.get("momentum_ok") == "Y":
                reason += ", and getting cheaper"
        else:
            action, reason = "HOLD", f"no red flags, but fails {', '.join(fails)}, so not adding"

    if action in ("SELL", "REVIEW"):
        note = cgt_timing_note(position, today)
        if note:
            reason += "; " + note
    return action, reason


def cgt_timing_note(position: PositionSummary, today: date) -> str | None:
    """Flags a parcel about to cross the 12-month CGT discount line, where
    waiting a few weeks could halve the tax on the gain."""
    if position.next_discount_date is None:
        return None
    days = (position.next_discount_date - today).days
    if 0 < days <= CGT_TIMING_WINDOW_DAYS:
        return (
            f"{_fmt_units(position.units_pending_discount)} units qualify for the CGT discount from "
            f"{position.next_discount_date:%d %b %Y} ({days} days), consider timing any sale"
        )
    return None
