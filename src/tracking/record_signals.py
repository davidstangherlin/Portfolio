"""Record tonight's signals for the track record (docs/AS_BUILT.md §21).

    python -m src.tracking.record_signals

Run by scripts/daily_refresh.ps1 straight after valuation. Safe to run
again: a date already recorded is left exactly as it was.
"""

from __future__ import annotations

import logging
import sys
from datetime import date

from src.config import get_session
from src.tracking.signals import RULES_VERSION, record_signals

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with get_session() as session:
        result = record_signals(session, date.today())
        session.commit()
    dates = ", ".join(d.isoformat() for d in sorted(result.dates)) or "no dates"
    logger.info("Recorded %d signals for %s (rules %s); %d already recorded and left unchanged; "
                "%d calls on people's holdings", result.recorded, dates, RULES_VERSION, result.already_recorded,
                result.personal)
    if result.stale:
        logger.warning("Not recorded, valuation older than the latest price (%d): %s",
                       len(result.stale), ", ".join(sorted(result.stale)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
