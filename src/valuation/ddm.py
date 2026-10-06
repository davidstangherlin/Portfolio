"""Two-stage Dividend Discount Model (DDM) for sectors where a standard
Free-Cash-Flow DCF doesn't apply.

Banks, insurers and REITs routinely report negative or balance-sheet-
dominated "free cash flow" under the conventional operating-CF-minus-capex
definition - loan book movements, policy reserve movements and property
revaluations dominate it, rather than the kind of reinvestment capex the
DCF model assumes. `engine.py`'s existing DCF path correctly skips these
companies rather than fabricating a number from a meaningless FCF figure
(docs/AS_BUILT.md known-issue #8), but that means Financial Services and
Real Estate companies almost never get a margin-of-safety figure at all.

Dividends are the natural analogue to FCF for these sectors: banks,
insurers and REITs are dividend-driven business models almost by
definition, and typically pay out a high, relatively stable share of
earnings. A Gordon-style two-stage DDM on the actual per-share dividend
stream is a more defensible intrinsic value for them than a DCF built on
a cash-flow figure that doesn't behave like one.

Same two-stage mechanics as `dcf.two_stage_dcf` (stage-1 explicit growth
for `stage1_years`, then a Gordon Growth terminal value), substituted onto
dividends-per-share instead of free-cash-flow:

    PV(stage1)  = sum_{t=1..n} D * (1+g)^t / (1+r)^t
    D_n         = D * (1+g)^n
    terminal    = D_n * (1+g_t) / (r - g_t)
    PV(terminal)= terminal / (1+r)^n
    intrinsic value per share = PV(stage1) + PV(terminal)

Unlike the FCF-based DCF, this is already a per-share figure and there is
no separate cash/debt netting step: dividends are paid out of post-tax,
post-financing earnings, so there's nothing left to add back or net off.
Likewise there's no `shares_outstanding` input (and so none of the
shares-outstanding estimation risk flagged as known-issue #3) - the
dividend-per-share figure from `financial_reports` is used directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.settings import LIVE

# Live values come from the settings registry (src/settings.py).
DEFAULT_DISCOUNT_RATE = LIVE.discount_rate
DEFAULT_GROWTH_RATE = LIVE.ddm_growth_rate  # dividend growth tends to be steadier/lower than FCF growth
DEFAULT_TERMINAL_GROWTH_RATE = LIVE.terminal_growth_rate
DEFAULT_STAGE1_YEARS = LIVE.stage1_years


@dataclass(frozen=True)
class DdmResult:
    intrinsic_value_per_share: Decimal | None


def two_stage_ddm(
    base_dividend_per_share: Decimal,
    growth_rate: Decimal = DEFAULT_GROWTH_RATE,
    stage1_years: int = DEFAULT_STAGE1_YEARS,
    terminal_growth_rate: Decimal = DEFAULT_TERMINAL_GROWTH_RATE,
    discount_rate: Decimal = DEFAULT_DISCOUNT_RATE,
) -> DdmResult:
    if discount_rate <= terminal_growth_rate:
        raise ValueError("discount_rate must exceed terminal_growth_rate for the terminal value to converge")

    if not base_dividend_per_share or base_dividend_per_share <= 0:
        return DdmResult(intrinsic_value_per_share=None)

    one = Decimal("1")
    pv_stage1 = Decimal("0")
    div_t = base_dividend_per_share
    for t in range(1, stage1_years + 1):
        div_t = div_t * (one + growth_rate)
        pv_stage1 += div_t / (one + discount_rate) ** t

    terminal_value = div_t * (one + terminal_growth_rate) / (discount_rate - terminal_growth_rate)
    pv_terminal = terminal_value / (one + discount_rate) ** stage1_years

    return DdmResult(intrinsic_value_per_share=pv_stage1 + pv_terminal)
