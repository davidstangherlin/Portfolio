"""Nightly Statistics step (docs/kb/features/statistics.md): each security's
volatility, beta, likely range and chances of reaching Sift's estimated
value and the analysts' target, into price_statistics.

    python -m src.analytics.run

The rule test needs no step: it is worked out from the track record's
monthly summary when the page asks (src/analytics/rules.py)."""

from __future__ import annotations

import logging
import sys
from datetime import date

from src.analytics import health
from src.analytics.prices import refresh

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from src.config import get_session
    with get_session() as session:
        counts = refresh(session, date.today())
        session.commit()
        fh = health.refresh(session, date.today())
        session.commit()
    logger.info("Statistics: %d securities, %d with a year or more of prices; beta against %s",
                counts["securities"], counts["with_volatility"], counts["market"] or "no market fund")
    logger.info("Financial health: %d shares, %d with an F-Score, %d in the Altman distress zone",
                fh["companies"], fh["f_scored"], fh["distress"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
