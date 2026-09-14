"""Two-stage Discounted Cash Flow (DCF) intrinsic valuation.

Stage 1 grows the latest Free Cash Flow (FCF) at `growth_rate` for
`stage1_years`, discounting each year back to present value. Stage 2 is a
Gordon Growth terminal value on the final stage-1 year's FCF, grown in
perpetuity at `terminal_growth_rate` and likewise discounted back.

    PV(stage1)  = sum_{t=1..n} FCF * (1+g)^t / (1+r)^t
    FCF_n       = FCF * (1+g)^n
    terminal    = FCF_n * (1+g_t) / (r - g_t)
    PV(terminal)= terminal / (1+r)^n

Equity value = PV(stage1) + PV(terminal) + cash_and_equivalents - total_debt
Intrinsic value per share = equity value / shares_outstanding

This is a standard, simplified FCFE-style two-stage DCF suitable as a
baseline value-investing screen - it is not a substitute for a full
company-specific model (working-capital swings, debt schedules, buybacks,
etc. are all ignored).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DEFAULT_DISCOUNT_RATE = Decimal("0.09")  # midpoint of the 8-10% baseline range
DEFAULT_GROWTH_RATE = Decimal("0.08")
DEFAULT_TERMINAL_GROWTH_RATE = Decimal("0.025")  # roughly long-run nominal GDP/inflation
DEFAULT_STAGE1_YEARS = 5


@dataclass(frozen=True)
class DcfResult:
    equity_value: Decimal
    intrinsic_value_per_share: Decimal | None


def two_stage_dcf(
    base_fcf: Decimal,
    shares_outstanding: Decimal | None,
    cash_and_equivalents: Decimal = Decimal("0"),
    total_debt: Decimal = Decimal("0"),
    growth_rate: Decimal = DEFAULT_GROWTH_RATE,
    stage1_years: int = DEFAULT_STAGE1_YEARS,
    terminal_growth_rate: Decimal = DEFAULT_TERMINAL_GROWTH_RATE,
    discount_rate: Decimal = DEFAULT_DISCOUNT_RATE,
) -> DcfResult:
    if discount_rate <= terminal_growth_rate:
        raise ValueError("discount_rate must exceed terminal_growth_rate for the terminal value to converge")

    one = Decimal("1")
    pv_stage1 = Decimal("0")
    fcf_t = base_fcf
    for t in range(1, stage1_years + 1):
        fcf_t = fcf_t * (one + growth_rate)
        pv_stage1 += fcf_t / (one + discount_rate) ** t

    terminal_value = fcf_t * (one + terminal_growth_rate) / (discount_rate - terminal_growth_rate)
    pv_terminal = terminal_value / (one + discount_rate) ** stage1_years

    equity_value = pv_stage1 + pv_terminal + cash_and_equivalents - total_debt

    if not shares_outstanding or shares_outstanding <= 0:
        return DcfResult(equity_value=equity_value, intrinsic_value_per_share=None)

    return DcfResult(
        equity_value=equity_value,
        intrinsic_value_per_share=equity_value / shares_outstanding,
    )


def margin_of_safety_percent(intrinsic_value: Decimal | None, current_price: Decimal | None) -> Decimal | None:
    """((Intrinsic Value - Current Price) / Intrinsic Value) * 100"""
    if not intrinsic_value or intrinsic_value <= 0 or current_price is None:
        return None
    return ((intrinsic_value - current_price) / intrinsic_value) * 100
