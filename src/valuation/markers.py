"""Decision markers layered on top of the core valuation (docs/AS_BUILT.md §8.7).

Each answers a question the four classic value criteria can't:

- Earnings quality: is reported profit actually turning into cash?
- Price position: is the price stabilising, or still falling?
- Dividend reliability: has the dividend been held, grown or cut?
- Data confidence: how much of this company's analysis rests on missing data?

All are deliberately simple, explainable rules - prompts to look closer,
not verdicts - consistent with the rest of this codebase's formulas.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from src.models import DailyPrice, FinancialReport
from src.settings import LIVE

# Live thresholds come from the settings registry (src/settings.py); each
# function also takes them as arguments so the admin console can try others.
EARNINGS_QUALITY_STRONG = LIVE.earnings_quality_strong
EARNINGS_QUALITY_ADEQUATE = LIVE.earnings_quality_adequate

MOVING_AVERAGE_DAYS = 200
MIN_BARS_FOR_52W_RANGE = 100
NEW_LOWS_RANGE_THRESHOLD = LIVE.new_lows_range

DIVIDEND_HISTORY_YEARS = 5
DIVIDEND_CUT_RATIO = LIVE.dividend_cut_ratio  # latest more than 10% below last year or the earlier median is a cut
DIVIDEND_GROWTH_RATIO = LIVE.dividend_growth_ratio


def cash_conversion_percent(reports: list[FinancialReport]) -> Decimal | None:
    """Operating cash flow / NPAT summed across the given reports, as a %.

    Summed rather than averaged per year so one odd year doesn't dominate.
    None for a loss-maker (a negative or zero profit makes the ratio
    meaningless) or when no report has both figures."""
    pairs = [
        (r.operating_cash_flow, r.net_profit_after_tax)
        for r in reports
        if r.operating_cash_flow is not None and r.net_profit_after_tax is not None
    ]
    if not pairs:
        return None
    total_profit = sum(npat for _, npat in pairs)
    if total_profit <= 0:
        return None
    return sum(ocf for ocf, _ in pairs) / total_profit * 100


def earnings_quality(cash_conversion: Decimal | None, strong: Decimal = EARNINGS_QUALITY_STRONG,
                     adequate: Decimal = EARNINGS_QUALITY_ADEQUATE) -> str | None:
    if cash_conversion is None:
        return None
    if cash_conversion >= strong:
        return "STRONG"
    if cash_conversion >= adequate:
        return "ADEQUATE"
    return "WEAK"


def price_vs_moving_average(closes: list[Decimal], window: int = MOVING_AVERAGE_DAYS) -> Decimal | None:
    """% the latest close sits above (+) or below (-) its `window`-day
    average. `closes` is newest first."""
    if len(closes) < window:
        return None
    average = sum(closes[:window]) / window
    if average <= 0:
        return None
    return (closes[0] / average - 1) * 100


def range_position(closes: list[Decimal]) -> Decimal | None:
    """Where the latest close sits in the low-high range of `closes`
    (newest first, expected to span ~52 weeks): 0 = at the low, 100 = at
    the high."""
    if len(closes) < MIN_BARS_FOR_52W_RANGE:
        return None
    low, high = min(closes), max(closes)
    if high == low:
        return None
    return (closes[0] - low) / (high - low) * 100


def price_signal(vs_200d: Decimal | None, range_pos: Decimal | None,
                 new_lows: Decimal = NEW_LOWS_RANGE_THRESHOLD) -> str | None:
    """'NEW LOWS' (below a 200-day average and in the bottom 10% of its
    52-week range - still falling), 'DOWNTREND' or 'UPTREND'."""
    if vs_200d is None:
        return None
    if vs_200d < 0 and range_pos is not None and range_pos <= new_lows:
        return "NEW LOWS"
    if vs_200d < 0:
        return "DOWNTREND"
    return "UPTREND"


def dividend_trend(reports: list[FinancialReport], cut_ratio: Decimal = DIVIDEND_CUT_RATIO,
                   growth_ratio: Decimal = DIVIDEND_GROWTH_RATIO) -> str | None:
    """'CUT' if the latest dividend is more than 10% below either last
    year's or the median of the earlier years in the window - a cut that
    still stands. A cut the company has since restored no longer counts:
    miners and energy producers vary their dividends with earnings by
    policy, and flagging every historical dip buried the cuts that matter.
    'GROWING' if the latest is more than 5% above the oldest, 'STEADY'
    otherwise, 'NONE' for a non-payer. `reports` is newest first. The year
    after a special dividend reads as a cut against last year, which it is
    in cash terms; the payout_ratio warning flags the special year itself,
    and the median keeps one special year from distorting the baseline."""
    values = [r.dividends_per_share for r in reversed(reports) if r.dividends_per_share is not None]
    if len(values) < 2:
        return None
    if all(v == 0 for v in values):
        return "NONE"
    latest, previous, earlier = values[-1], values[-2], values[:-1]
    if latest < previous * cut_ratio or latest < median(earlier) * cut_ratio:
        return "CUT"
    if latest > values[0] * growth_ratio:
        return "GROWING"
    return "STEADY"


def data_confidence(
    price: DailyPrice, report: FinancialReport, report_count: int, price_history_count: int
) -> str:
    """Share of key valuation inputs actually present. Dividends aren't
    counted - a non-payer isn't missing data."""
    fields = [
        price.close_price, price.market_cap,
        report.eps, report.net_profit_after_tax, report.revenue, report.total_equity,
        report.total_debt, report.operating_cash_flow, report.free_cash_flow,
    ]
    present = sum(1 for f in fields if f is not None)
    present += report_count >= 3
    present += price_history_count >= MOVING_AVERAGE_DAYS
    ratio = Decimal(present) / Decimal(len(fields) + 2)
    if ratio >= Decimal("0.9"):
        return "HIGH"
    if ratio >= Decimal("0.7"):
        return "MEDIUM"
    return "LOW"
