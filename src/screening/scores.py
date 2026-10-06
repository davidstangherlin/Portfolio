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
from src.settings import LIVE, ModelSettings, display

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


def score_card(row: dict, report: FinancialReport | None = None, settings: ModelSettings = LIVE) -> dict[str, list[Check]]:
    """`row` is one annotated screener row (screen_asx.annotate_row) plus
    `roic` and `graham_number`; `report` is the latest FY financial report,
    used for the balance-sheet health checks. Thresholds come from
    `settings` (src/settings.py), and each label states the one used."""
    s = settings
    n = display
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
            Check(f"Margin of safety above {n(s.min_margin_of_safety)}%", _gt(mos, s.min_margin_of_safety)),
            Check(f"Margin of safety above {n(s.score_mos_strong)}%", _gt(mos, s.score_mos_strong)),
            Check(f"P/E between 0 and {n(s.score_max_pe)}", _between(row.get("pe_ratio"), 0, s.score_max_pe)),
            Check(f"P/B between 0 and {n(s.score_max_pb)}", _between(row.get("pb_ratio"), 0, s.score_max_pb)),
            Check("Price below Graham Number", None if price is None or graham is None else price < graham),
        ],
        "Performance": [
            Check(f"ROE above {n(s.min_roe)}%", _gt(row.get("roe"), s.min_roe)),
            Check(f"ROE above {n(s.score_roe_high)}%", _gt(row.get("roe"), s.score_roe_high)),
            Check(f"ROIC above {n(s.score_min_roic)}%", _gt(row.get("roic"), s.score_min_roic)),
            Check("ROE and revenue not declining", _in(row.get("fundamentals_trend"), ("STABLE", "IMPROVING"))),
            Check(f"Profit backed by cash ({n(s.earnings_quality_adequate)}%+)", _in(row.get("earnings_quality"), ("STRONG", "ADEQUATE"))),
            Check("Cash flow exceeds profit", _in(row.get("earnings_quality"), ("STRONG",))),
        ],
        "Health": [
            Check(f"Debt/equity below {n(s.max_debt_equity)}", _lt(de, s.max_debt_equity)),
            Check(f"Debt/equity below {n(s.score_debt_equity_low)}", _lt(de, s.score_debt_equity_low)),
            Check("More cash than debt", None if cash is None or debt is None else cash >= debt),
            Check("Positive shareholders' equity", _gt(equity, 0)),
            Check("Positive free cash flow", _gt(fcf, 0)),
            Check("Profitable", _gt(npat, 0)),
        ],
        "Dividend": [
            Check("Pays a dividend", pays_dividend),
            Check(f"Grossed-up yield above {n(s.min_yield)}%", _gt(gross_yield, s.min_yield)),
            Check(f"Grossed-up yield above {n(s.score_yield_high)}%", _gt(gross_yield, s.score_yield_high)),
            Check(f"Payout ratio {n(s.score_max_payout)}% or less", None if payout is None else payout <= s.score_max_payout),
            Check("No standing dividend cut", _in(trend, ("STEADY", "GROWING"))),
            Check("Dividend growing", _in(trend, ("GROWING",))),
        ],
        "Momentum": [
            Check("Price above 200-day average", _in(signal, ("UPTREND",))),
            Check("Not making new 52-week lows", _in(signal, ("UPTREND", "DOWNTREND"))),
            Check("In upper half of 52-week range" if s.score_upper_range == 50 else f"Above {n(s.score_upper_range)}% of 52-week range",
                  _gt(row.get("range_position_52w"), s.score_upper_range)),
            Check("Margin of safety improving (30 days)", _gt(row.get("margin_of_safety_trend"), 0)),
            Check(f"Margin of safety up {n(s.min_mos_trend)}+ points", None if row.get("margin_of_safety_trend") is None else row.get("momentum_ok") == "Y"),
            Check("ROE or revenue improving", _in(row.get("fundamentals_trend"), ("IMPROVING",))),
        ],
    }


def axis_scores(card: dict[str, list[Check]]) -> dict[str, int]:
    """Checks passed per axis, 0 to CHECKS_PER_AXIS. No-data counts as not passed."""
    return {axis: sum(1 for c in checks if c.passed) for axis, checks in card.items()}
