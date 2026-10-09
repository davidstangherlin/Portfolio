"""The Track record page's figures (docs/AS_BUILT.md §21): is Sift
accurate, what did I miss, and what should I look at now.

- Verdict: per action and horizon, from the permanent monthly summary
  (track_record_monthly), so it covers the whole history, not just the 14
  months of detail. Confidence comes from the number of signals.
- Missed opportunities and calls that saved money: from the detailed
  outcomes (last 14 months).
- Still actionable: today's signals of the kind that has done best.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from src.accounts import current_user_id
from src.tracking.signals import HORIZONS_MONTHS, RULES_VERSION

TOO_EARLY_BELOW = 30        # fewer signals than this: "too early"
SOLID_ABOVE = 100           # more than this: "solid"; in between: "moderate"
MISSED_EXCESS = Decimal("10")   # beat (or trailed) the average by more than this many points
PURCHASE_WINDOW_DAYS = 30       # a buy this soon after the signal means you acted on it
NEW_SIGNAL_DAYS = 7
MOVED_ON_LOOKBACK_DAYS = 90
ORDER_CHECK = ("BUY", "WATCH", "AVOID")
BUY_SIDE = ("BUY", "INVESTIGATE", "ACCUMULATE")
LIST_LIMIT = 20


def confidence(signals: int) -> str:
    if signals < TOO_EARLY_BELOW:
        return "too early"
    if signals > SOLID_ABOVE:
        return "solid"
    return "moderate"


def versions(session) -> list[str]:
    rows = session.execute(text("""
        SELECT rules_version FROM track_record_monthly
        UNION SELECT rules_version FROM signal_snapshots ORDER BY 1 DESC
    """)).scalars().all()
    return list(rows) or [RULES_VERSION]


def verdict(session, version: str | None) -> dict:
    """{horizon: {"actions": [...], "order": {...}}} combined across months,
    weighting each month's averages by its number of signals."""
    rows = session.execute(text("""
        SELECT action, horizon_months, SUM(signals) AS signals, SUM(beat_benchmark) AS beat,
               SUM(avg_excess * signals) / NULLIF(SUM(signals), 0) AS avg_excess,
               SUM(avg_return * signals) / NULLIF(SUM(signals), 0) AS avg_return,
               MIN(month) AS first_month, MAX(month) AS last_month
        FROM track_record_monthly
        WHERE (CAST(:version AS TEXT) IS NULL OR rules_version = :version)
        GROUP BY action, horizon_months
    """), {"version": version}).mappings().all()
    out = {}
    for months in HORIZONS_MONTHS:
        actions = []
        for r in (r for r in rows if r["horizon_months"] == months):
            n = int(r["signals"])
            actions.append({"action": r["action"], "signals": n, "beat": int(r["beat"]),
                            "beat_rate": Decimal(int(r["beat"]) * 100) / n if n else None,
                            "avg_excess": r["avg_excess"], "avg_return": r["avg_return"],
                            "confidence": confidence(n), "first_month": r["first_month"], "last_month": r["last_month"]})
        actions.sort(key=lambda a: (-(a["avg_excess"] if a["avg_excess"] is not None else Decimal("-1e9")), a["action"]))
        out[months] = {"actions": actions, "order": order_check(actions)}
    return out


def order_check(actions: list[dict]) -> dict:
    """Do BUY, WATCH and AVOID line up in that order on average excess
    return? Only judged once each has enough signals."""
    by = {a["action"]: a for a in actions}
    present = [by.get(name) for name in ORDER_CHECK]
    if any(a is None or a["confidence"] == "too early" for a in present):
        return {"status": "too early", "actions": list(ORDER_CHECK)}
    values = [a["avg_excess"] for a in present]
    in_order = values[0] > values[1] > values[2]
    return {"status": "in order" if in_order else "out of order", "actions": list(ORDER_CHECK)}


def monthly(session, version: str | None) -> list[dict]:
    return [dict(r) for r in session.execute(text("""
        SELECT month, action, horizon_months, SUM(signals) AS signals, SUM(beat_benchmark) AS beat,
               SUM(avg_excess * signals) / NULLIF(SUM(signals), 0) AS avg_excess
        FROM track_record_monthly
        WHERE (CAST(:version AS TEXT) IS NULL OR rules_version = :version)
        GROUP BY month, action, horizon_months ORDER BY month DESC, action
    """), {"version": version}).mappings()]


_LATEST_OUTCOME = """
    SELECT DISTINCT ON (s.company_id, s.snapshot_date)
           c.asx_code, c.company_name, s.snapshot_date, s.action, s.held, s.price, s.rules_version,
           o.horizon_months, o.total_return, o.excess_return, o.end_price, o.end_date, o.delisted
    FROM signal_outcomes o
    JOIN signal_snapshots s USING (company_id, snapshot_date)
    JOIN companies c ON c.company_id = s.company_id
    WHERE (CAST(:version AS TEXT) IS NULL OR s.rules_version = :version)
    ORDER BY s.company_id, s.snapshot_date, o.horizon_months DESC
"""


def _bought_soon_after(session) -> set[tuple[str, date]]:
    """The current user's purchases (src/accounts.py, §33)."""
    return {(code, d) for code, d in session.execute(text("""
        SELECT h.asx_code, h.buy_date FROM holdings h JOIN portfolios p USING (portfolio_id) WHERE p.owner_id = :o"""),
        {"o": current_user_id(session)})}


def _acted(purchases, code: str, signal_date: date) -> bool:
    end = signal_date + timedelta(days=PURCHASE_WINDOW_DAYS)
    return any(c == code and signal_date <= d <= end for c, d in purchases)


def _first_per_company(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["snapshot_date"]):
        if r["asx_code"] not in seen:
            seen.add(r["asx_code"])
            out.append(r)
    return out


def _now(r: dict, current: dict[str, dict], threshold: Decimal) -> dict:
    row = current.get(r["asx_code"])
    mos = row["margin_of_safety_percent"] if row else None
    return r | {"price_now": row["current_price"] if row else None, "margin_of_safety_now": mos,
                "action_now": row["action"] if row else None,
                "still_undervalued": mos is not None and mos > threshold}


def missed_and_saved(session, version: str | None, current: dict[str, dict], threshold: Decimal,
                     watched: dict[str, list[str]]) -> tuple[list[dict], list[dict]]:
    """Missed: BUY or INVESTIGATE on shares not held, not bought within 30
    days, that beat the average by more than 10 points at their latest
    measured horizon. Saved: AVOID (not held) and SELL (held) calls that
    trailed the average by more than 10 points. First call per company."""
    rows = [dict(r) for r in session.execute(text(_LATEST_OUTCOME), {"version": version}).mappings()]
    purchases = _bought_soon_after(session)
    missed = [r for r in rows
              if r["action"] in ("BUY", "INVESTIGATE") and not r["held"] and r["excess_return"] is not None
              and r["excess_return"] > MISSED_EXCESS and not _acted(purchases, r["asx_code"], r["snapshot_date"])]
    saved = [r for r in rows
             if ((r["action"] == "AVOID" and not r["held"]) or (r["action"] == "SELL" and r["held"]))
             and r["excess_return"] is not None and r["excess_return"] < -MISSED_EXCESS]
    def finish(items, key):
        items = _first_per_company(items)
        items.sort(key=key)
        return [_now(r, current, threshold) | {"watchlists": watched.get(r["asx_code"], [])} for r in items[:LIST_LIMIT]]
    return (finish(missed, lambda r: -r["excess_return"]), finish(saved, lambda r: r["excess_return"]))


def proven_actions(v: dict) -> tuple[list[str], bool, int | None]:
    """Buy-side actions that have beaten the average with at least moderate
    confidence, judged at 3 months (or 1 month while 3 isn't available).
    Until something is proven, BUY stands in on the rules' own terms."""
    for months in (3, 1):
        proven = [a["action"] for a in v[months]["actions"]
                  if a["action"] in BUY_SIDE and a["confidence"] != "too early"
                  and a["avg_excess"] is not None and a["avg_excess"] > 0]
        if proven:
            return proven, True, months
    return ["BUY"], False, None


def actionable(session, current_rows: list[dict], proven: list[str], threshold: Decimal,
               watched: dict[str, list[str]]) -> dict:
    """Today's signals of a proven kind, grouped by freshness, and the ones
    that have moved on in the last 90 days."""
    latest = session.execute(text("SELECT MAX(snapshot_date) FROM signal_snapshots")).scalar_one()
    if latest is None:
        return {"as_of": None, "new": [], "open": [], "moved_on": []}
    history = session.execute(text("""
        SELECT c.asx_code, s.snapshot_date, s.action, s.price, s.held
        FROM signal_snapshots s JOIN companies c ON c.company_id = s.company_id
        WHERE s.snapshot_date >= :since ORDER BY c.asx_code, s.snapshot_date
    """), {"since": latest - timedelta(days=400)}).mappings().all()
    by_code: dict[str, list] = {}
    for h in history:
        by_code.setdefault(h["asx_code"], []).append(h)

    def entered(code: str, action: str):
        """The first snapshot of the current unbroken run of `action`."""
        run = None
        for h in by_code.get(code, []):
            run = (run or h) if h["action"] == action else None
        return run

    new, still_open = [], []
    current = {r["asx_code"]: r for r in current_rows}
    for r in current_rows:
        if r["action"] not in proven or r["margin_of_safety_percent"] is None or r["margin_of_safety_percent"] <= threshold:
            continue
        start = entered(r["asx_code"], r["action"])
        item = {"asx_code": r["asx_code"], "company_name": r["company_name"], "action": r["action"],
                "since": start["snapshot_date"] if start else None, "price_then": start["price"] if start else None,
                "price_now": r["current_price"], "margin_of_safety_now": r["margin_of_safety_percent"],
                "watchlists": watched.get(r["asx_code"], [])}
        (new if start is None or (latest - start["snapshot_date"]).days < NEW_SIGNAL_DAYS else still_open).append(item)

    moved = []
    since = latest - timedelta(days=MOVED_ON_LOOKBACK_DAYS)
    for code, hist in by_code.items():
        signals = [h for h in hist if h["snapshot_date"] >= since and h["action"] in proven and not h["held"]]
        now = current.get(code)
        if not signals or now is None:
            continue
        still = now["action"] in proven and now["margin_of_safety_percent"] is not None and now["margin_of_safety_percent"] > threshold
        if still:
            continue
        last = signals[-1]
        mos = now["margin_of_safety_percent"]
        out_of_zone = mos is None or mos <= threshold
        if now["held"] is not None:
            why = "you bought it"
        elif out_of_zone and last["price"] and now["current_price"] > last["price"]:
            why = "price rose out of the buy zone"
        elif out_of_zone:
            why = "estimated value fell" if mos is not None else "no longer valued"
        else:
            why = f"now {now['action']}"
        moved.append({"asx_code": code, "company_name": now["company_name"], "action": last["action"],
                      "since": last["snapshot_date"], "price_then": last["price"], "price_now": now["current_price"],
                      "margin_of_safety_now": mos, "action_now": now["action"], "why": why,
                      "watchlists": watched.get(code, [])})

    def order(items):
        return sorted(items, key=lambda i: (not i["watchlists"], -(i["margin_of_safety_now"] or 0)))
    return {"as_of": latest, "new": order(new), "open": order(still_open),
            "moved_on": sorted(moved, key=lambda i: i["since"], reverse=True)[:LIST_LIMIT]}



def headline(session) -> dict | None:
    """The dashboard's one-line result: BUY at 3 months, or 1 month until
    3-month results exist. None before any results."""
    v = verdict(session, None)
    for months in (3, 1):
        buy = next((a for a in v[months]["actions"] if a["action"] == "BUY"), None)
        if buy:
            return buy | {"horizon_months": months}
    return None
