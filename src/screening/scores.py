"""Score wheel for the web GUI's company page (docs/AS_BUILT.md §20).

Five dimensions, six yes/no checks each, so every score is a count out of
six that can be traced back to named rules - the same transparency as the
rest of the screener, rather than a weighted black-box rating. Each check
is True (passes), False (fails) or None (no data). A missing value never
counts as a pass, consistent with the core value tests.

The checks reuse the screener's own thresholds and markers wherever one
exists, so the wheel can't contradict the Y/N columns or the suggested
action.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.models import FinancialReport

AXES = ("Value", "Performance", "Health", "Dividend", "Momentum")
CHECKS_PER_AXIS = 6


@dataclass(frozen=True)
class Check:
    label: str
    passed: bool | None  # None = not enough data to judge


def _gt(value, threshold) -> bool | None:
    return None if value is None else value > Decimal(str(threshold))


def _lt(value, threshold) -> bool | None:
    return None if value is None else value < Decimal(str(threshold))


def _between(value, low, high) -> bool | None:
    """low < value < high: a P/E or P/B only counts as cheap when positive."""
    return None if value is None else Decimal(str(low)) < value < Decimal(str(high))


def _in(value, allowed: tuple[str, ...]) -> bool | None:
    return None if value is None else value in allowed


def score_card(row: dict, report: FinancialReport | None = None) -> dict[str, list[Check]]:
    """`row` is one annotated screener row (screen_asx.annotate_row) plus
    `roic` and `graham_number`; `report` is the latest FY financial report,
    used for the balance-sheet health checks."""
    mos = row.get("margin_of_safety_percent")
    price = row.get("current_price")
    graham = row.get("graham_number")
    de = row.get("debt_to_equity")
    gross_yield = row.get("grossed_up_dividend_yield")
    payout = row.get("payout_ratio")
    signal = row.get("price_signal")

    cash = report.cash_and_equivalents if report else None
    debt = report.total_debt if report else None
    equity = report.total_equity if report else None
    fcf = report.free_cash_flow if report else None
    npat = report.net_profit_after_tax if report else None

    trend = row.get("dividend_trend")
    if gross_yield is not None:
        pays_dividend = gross_yield > 0
    else:
        pays_dividend = None if trend is None else trend != "NONE"

    return {
        "Value": [
            Check("Trading below estimated value", _gt(mos, 0)),
            Check("Margin of safety above 20%", _gt(mos, 20)),
            Check("Margin of safety above 40%", _gt(mos, 40)),
            Check("P/E between 0 and 15", _between(row.get("pe_ratio"), 0, 15)),
            Check("P/B between 0 and 1.5", _between(row.get("pb_ratio"), 0, 1.5)),
            Check("Price below Graham Number", None if price is None or graham is None else price < graham),
        ],
        "Performance": [
            Check("ROE above 12%", _gt(row.get("roe"), 12)),
            Check("ROE above 20%", _gt(row.get("roe"), 20)),
            Check("ROIC above 10%", _gt(row.get("roic"), 10)),
            Check("ROE and revenue not declining", _in(row.get("fundamentals_trend"), ("STABLE", "IMPROVING"))),
            Check("Profit backed by cash (80%+)", _in(row.get("earnings_quality"), ("STRONG", "ADEQUATE"))),
            Check("Cash flow exceeds profit", _in(row.get("earnings_quality"), ("STRONG",))),
        ],
        "Health": [
            Check("Debt/equity below 0.8", _lt(de, 0.8)),
            Check("Debt/equity below 0.4", _lt(de, 0.4)),
            Check("More cash than debt", None if cash is None or debt is None else cash >= debt),
            Check("Positive shareholders' equity", _gt(equity, 0)),
            Check("Positive free cash flow", _gt(fcf, 0)),
            Check("Profitable", _gt(npat, 0)),
        ],
        "Dividend": [
            Check("Pays a dividend", pays_dividend),
            Check("Grossed-up yield above 4.5%", _gt(gross_yield, 4.5)),
            Check("Grossed-up yield above 6%", _gt(gross_yield, 6)),
            Check("Payout ratio 100% or less", None if payout is None else payout <= 100),
            Check("No standing dividend cut", _in(trend, ("STEADY", "GROWING"))),
            Check("Dividend growing", _in(trend, ("GROWING",))),
        ],
        "Momentum": [
            Check("Price above 200-day average", _in(signal, ("UPTREND",))),
            Check("Not making new 52-week lows", _in(signal, ("UPTREND", "DOWNTREND"))),
            Check("In upper half of 52-week range", _gt(row.get("range_position_52w"), 50)),
            Check("Margin of safety improving (30 days)", _gt(row.get("margin_of_safety_trend"), 0)),
            Check("Margin of safety up 5+ points", None if row.get("margin_of_safety_trend") is None else row.get("momentum_ok") == "Y"),
            Check("ROE or revenue improving", _in(row.get("fundamentals_trend"), ("IMPROVING",))),
        ],
    }


def axis_scores(card: dict[str, list[Check]]) -> dict[str, int]:
    """Checks passed per axis, 0 to CHECKS_PER_AXIS. No-data counts as not passed."""
    return {axis: sum(1 for c in checks if c.passed) for axis, checks in card.items()}
