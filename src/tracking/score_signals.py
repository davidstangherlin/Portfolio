"""Score recorded signals and keep the track record tidy (docs/AS_BUILT.md §21).

    python -m src.tracking.score_signals

Run by scripts/daily_refresh.ps1 after the signal record. In one
transaction: fills in every 1, 3, 6 and 12-month outcome the market data
has now reached, rebuilds the monthly summary, then deletes detail older
than 14 months. Safe to run again: outcomes already scored are kept.
"""

from __future__ import annotations

import logging
import sys
from datetime import date

from src.config import get_session
from src.tracking.outcomes import RETENTION_MONTHS, retention_cutoff, update_track_record

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    today = date.today()
    with get_session() as session:
        run = update_track_record(session, today)
        session.commit()
    logger.info("Scored %d outcomes (market data to %s); %d monthly summary rows refreshed; "
                "%d signals older than %s deleted (%d-month retention)",
                run.outcomes, run.market_date, run.summary_rows, run.pruned, retention_cutoff(today), RETENTION_MONTHS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
