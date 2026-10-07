"""What each ETF and LIC holds (docs/AS_BUILT.md §26.3): description, asset
mix, top 10 holdings, sector weightings and bond details from Yahoo
Finance's fund data, refreshed weekly (a seventh of the funds each night,
src/ingestion/rolling.py). Yahoo lists LICs as companies, so they get the
description only; their holdings are in each LIC's own monthly report.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.ingestion.rolling import nightly_share
from src.ingestion.yahoo_client import LOOK_THROUGH_PERCENT, FundProfile, YahooClient

logger = logging.getLogger(__name__)

# A feeder fund stored before look-through existed (its one big holding
# not yet looked through) counts as never fetched, so it's fixed at once.
_FUNDS = text("""
    SELECT c.asx_code, c.company_id,
           CASE WHEN p.look_through_symbol IS NULL AND EXISTS (
                    SELECT 1 FROM fund_holdings h WHERE h.company_id = c.company_id AND h.rank = 1
                      AND h.weight_percent >= :feeder AND h.symbol IS NOT NULL)
                THEN NULL ELSE p.fetched_at END AS fetched_at
    FROM companies c LEFT JOIN fund_profiles p ON p.company_id = c.company_id
    WHERE c.security_type IN ('ETF', 'LIC') AND c.is_active = TRUE
    ORDER BY c.asx_code
""")


def store_profile(session: Session, company_id, p: FundProfile) -> None:
    session.execute(text("""
        INSERT INTO fund_profiles (company_id, fetched_at, description, stock_percent, bond_percent, cash_percent,
                                   other_percent, sector_weightings, bond_ratings, duration_years, maturity_years, top10_percent,
                                   look_through_symbol, look_through_name, look_through_percent)
        VALUES (:c, CURRENT_TIMESTAMP, :d, :s, :b, :cash, :o, CAST(:sw AS JSONB), CAST(:br AS JSONB), :dur, :mat, :top,
                :lts, :ltn, :ltp)
        ON CONFLICT (company_id) DO UPDATE SET fetched_at = CURRENT_TIMESTAMP, description = EXCLUDED.description,
            stock_percent = EXCLUDED.stock_percent, bond_percent = EXCLUDED.bond_percent, cash_percent = EXCLUDED.cash_percent,
            other_percent = EXCLUDED.other_percent, sector_weightings = EXCLUDED.sector_weightings,
            bond_ratings = EXCLUDED.bond_ratings, duration_years = EXCLUDED.duration_years,
            maturity_years = EXCLUDED.maturity_years, top10_percent = EXCLUDED.top10_percent,
            look_through_symbol = EXCLUDED.look_through_symbol, look_through_name = EXCLUDED.look_through_name,
            look_through_percent = EXCLUDED.look_through_percent
    """), {"c": company_id, "d": p.description, "s": p.stock_percent, "b": p.bond_percent, "cash": p.cash_percent,
           "o": p.other_percent, "sw": json.dumps(p.sector_weightings) if p.sector_weightings else None,
           "br": json.dumps(p.bond_ratings) if p.bond_ratings else None, "dur": p.duration_years,
           "mat": p.maturity_years, "top": p.top10_percent, "lts": p.look_through_symbol and p.look_through_symbol[:30],
           "ltn": p.look_through_name and p.look_through_name[:255], "ltp": p.look_through_percent})
    session.execute(text("DELETE FROM fund_holdings WHERE company_id = :c"), {"c": company_id})
    for x in p.holdings or []:
        session.execute(text("""
            INSERT INTO fund_holdings (company_id, rank, symbol, name, weight_percent) VALUES (:c, :r, :s, :n, :w)
        """), {"c": company_id, "r": x.rank, "s": (x.symbol or None) and x.symbol[:30], "n": x.name, "w": x.weight_percent})


def ingest_fund_profiles(session: Session, today: date | None = None, all_now: bool = False, delay_seconds: float = 0.0,
                         client_factory=YahooClient) -> dict[str, bool]:
    """Fetch and store tonight's share of fund profiles. Returns {code:
    stored}. A failed fetch keeps the old profile and is retried next run."""
    rows = session.execute(_FUNDS, {"feeder": LOOK_THROUGH_PERCENT}).all()
    ids = {code: cid for code, cid, _ in rows}
    codes = nightly_share([code for code, _, _ in rows], {code: at for code, _, at in rows}, today or date.today(), all_now)
    logger.info("Fund profiles: %d of %d ETFs and LICs due tonight", len(codes), len(rows))
    results = {}
    for i, code in enumerate(codes, start=1):
        try:
            profile = client_factory(code).get_fund_profile()
            if profile is not None:
                store_profile(session, ids[code], profile)
                session.commit()
            results[code] = profile is not None
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] Fund profile failed for %s - skipping", i, len(codes), code)
            results[code] = False
        if delay_seconds and i < len(codes):
            time.sleep(delay_seconds)
    with_holdings = sum(1 for c in codes if results.get(c) and session.execute(
        text("SELECT 1 FROM fund_holdings WHERE company_id = :c LIMIT 1"), {"c": ids[c]}).first())
    logger.info("Fund profiles complete: %d/%d stored, %d with holdings", sum(results.values()), len(codes), with_holdings)
    return results


def profile_payload(session: Session, company_id) -> dict | None:
    """What the fund page shows, or None before the first fetch."""
    row = session.execute(text("SELECT * FROM fund_profiles WHERE company_id = :c"), {"c": company_id}).mappings().first()
    if row is None:
        return None
    out = dict(row)
    out.pop("company_id")
    out["holdings"] = [dict(r) for r in session.execute(text(
        "SELECT rank, symbol, name, weight_percent FROM fund_holdings WHERE company_id = :c ORDER BY rank"),
        {"c": company_id}).mappings()]
    return out
