"""Rebuild Sift's search index on demand (docs/AS_BUILT.md §32).

    python -m src.search.reindex                 # everything
    python -m src.search.reindex --area market   # one area: market, coattail, personal, help, pages
    python -m src.search.reindex --trigger nightly

The nightly job (scripts/daily_refresh.ps1) runs it after the data refresh;
the admin console's Rebuild button does the same."""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import get_session
from src.search.indexer import AREAS, reindex


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild Sift's search index.")
    parser.add_argument("--area", action="append", choices=AREAS, help="rebuild only this area (repeatable)")
    parser.add_argument("--trigger", default="manual", choices=("manual", "nightly", "startup", "saved"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with get_session() as session:
        counts = reindex(session, args.area or AREAS, args.trigger)
        session.commit()
    print("Search index rebuilt: " + ", ".join(f"{a} {n}" for a, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
