"""Analyst ratings, price targets and holders from Yahoo Finance
(docs/AS_BUILT.md §29), refreshed weekly rather than nightly: each night
fetches the seventh of the shares whose data is oldest, so every company
is refreshed about once a week without adding ~1,500 Yahoo requests to
every run. Shown on the company page for context only; nothing here
feeds Sift's valuations, scores or signals.
"""

from __future__ import annotations

import logging
import time
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.ingestion.rolling import nightly_share
from src.ingestion.yahoo_client import Insights, YahooClient

logger = logging.getLogger(__name__)

_FETCHED = text("""
    SELECT c.asx_code, i.fetched_at
    FROM companies c LEFT JOIN company_insights i ON i.company_id = c.company_id
    WHERE c.asx_code = ANY(:codes) AND c.security_type = 'SHARE' AND c.is_active = TRUE
""")


def due_for_refresh(session: Session, asx_codes: list[str], today: date, all_now: bool = False) -> list[str]:
    """The shares to fetch tonight: those never fetched first, then the
    oldest, up to a seventh of the list (all of them with `all_now`). A
    company fetched within the last week is never due. Codes that aren't
    active shares in the database are left out."""
    fetched = dict(session.execute(_FETCHED, {"codes": list(asx_codes)}).all())
    return nightly_share([c for c in asx_codes if c in fetched], fetched, today, all_now)


def store_insights(session: Session, company_id, insights: Insights) -> None:
    """Replace the company's insights and top holders; add or update its
    monthly rating counts (older months are kept as history)."""
    fields = ("recommendation_key", "recommendation_mean", "analyst_count", "target_low", "target_mean",
              "target_median", "target_high", "insiders_percent", "institutions_percent",
              "institutions_float_percent", "institutions_count")
    values = {f: getattr(insights, f) for f in fields}
    session.execute(text(f"""
        INSERT INTO company_insights (company_id, fetched_at, {", ".join(fields)})
        VALUES (:company_id, CURRENT_TIMESTAMP, {", ".join(":" + f for f in fields)})
        ON CONFLICT (company_id) DO UPDATE SET fetched_at = CURRENT_TIMESTAMP,
            {", ".join(f"{f} = EXCLUDED.{f}" for f in fields)}
    """), {"company_id": company_id, **values})

    for r in insights.ratings or []:
        session.execute(text("""
            INSERT INTO analyst_ratings (company_id, rating_month, strong_buy, buy, hold, sell, strong_sell)
            VALUES (:c, :m, :sb, :b, :h, :s, :ss)
            ON CONFLICT (company_id, rating_month) DO UPDATE SET strong_buy = EXCLUDED.strong_buy,
                buy = EXCLUDED.buy, hold = EXCLUDED.hold, sell = EXCLUDED.sell, strong_sell = EXCLUDED.strong_sell
        """), {"c": company_id, "m": r.rating_month, "sb": r.strong_buy, "b": r.buy, "h": r.hold,
               "s": r.sell, "ss": r.strong_sell})

    session.execute(text("DELETE FROM top_holders WHERE company_id = :c"), {"c": company_id})
    for kind, holders in (("FUND", insights.funds), ("INSTITUTION", insights.institutions)):
        for x in holders or []:
            session.execute(text("""
                INSERT INTO top_holders (company_id, holder_kind, rank, holder, shares, percent_held, value,
                                         percent_change, date_reported)
                VALUES (:c, :k, :r, :n, :sh, :p, :v, :pc, :d)
            """), {"c": company_id, "k": kind, "r": x.rank, "n": x.holder, "sh": x.shares, "p": x.percent_held,
                   "v": x.value, "pc": x.percent_change, "d": x.date_reported})


def ingest_insights(session: Session, asx_codes: list[str], today: date | None = None,
                    delay_seconds: float = 0.0, all_now: bool = False, client_factory=YahooClient) -> dict[str, bool]:
    """Fetch and store tonight's share of insights. Returns {asx_code:
    stored}. A failed fetch leaves the old data and is retried next run."""
    today = today or date.today()
    codes = due_for_refresh(session, asx_codes, today, all_now)
    ids = dict(session.execute(text("SELECT asx_code, company_id FROM companies WHERE asx_code = ANY(:c)"),
                               {"c": codes}).all())
    logger.info("Analyst and holder data: %d of %d shares due tonight", len(codes), len(asx_codes))
    results: dict[str, bool] = {}
    for i, code in enumerate(codes, start=1):
        try:
            insights = client_factory(code).get_insights(today)
            if insights is not None:
                store_insights(session, ids[code], insights)
                session.commit()
            results[code] = insights is not None
        except Exception:
            session.rollback()
            logger.exception("[%d/%d] Analyst and holder data failed for %s - skipping", i, len(codes), code)
            results[code] = False
        if delay_seconds and i < len(codes):
            time.sleep(delay_seconds)
    return results


RATING_MONTHS = 4  # as many months as Yahoo gives; older stored months stay as history


def insights_payload(session: Session, company_id, price) -> dict | None:
    """What the company page shows, or None if nothing has been fetched yet.
    Each holder's value is restated at today's price (`value_now`), so it's
    in the share's own currency and current."""
    row = session.execute(text("SELECT * FROM company_insights WHERE company_id = :c"), {"c": company_id}).mappings().first()
    if row is None:
        return None
    ratings = [dict(r) for r in session.execute(text("""
        SELECT rating_month, strong_buy, buy, hold, sell, strong_sell FROM analyst_ratings
        WHERE company_id = :c ORDER BY rating_month DESC LIMIT :n
    """), {"c": company_id, "n": RATING_MONTHS}).mappings()][::-1]
    holders = {"FUND": [], "INSTITUTION": []}
    for r in session.execute(text("""
        SELECT holder_kind, holder, shares, percent_held, percent_change, date_reported FROM top_holders
        WHERE company_id = :c ORDER BY holder_kind, rank
    """), {"c": company_id}).mappings():
        h = dict(r)
        kind = h.pop("holder_kind")
        h["value_now"] = (h["shares"] * price).quantize(1) if h["shares"] is not None and price else None
        holders[kind].append(h)
    out = dict(row)
    out.pop("company_id")
    out.update(ratings=ratings, funds=holders["FUND"], institutions=holders["INSTITUTION"])
    return out
