"""Graham Number - Benjamin Graham's quick intrinsic-value screen.

    Graham Number = sqrt(22.5 * EPS * BVPS)

22.5 = 15 (Graham's ceiling P/E) x 1.5 (his ceiling P/B). Undefined
(returns None) whenever EPS or book value per share is zero or negative,
since a value stock with negative earnings or equity fails Graham's
criteria outright rather than producing a meaningless number.
"""

from __future__ import annotations

from decimal import Decimal


def book_value_per_share(total_equity: Decimal | None, shares_outstanding: Decimal | None) -> Decimal | None:
    if not total_equity or not shares_outstanding or shares_outstanding <= 0:
        return None
    return total_equity / shares_outstanding


def graham_number(eps: Decimal | None, bvps: Decimal | None) -> Decimal | None:
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return (Decimal("22.5") * eps * bvps).sqrt()
