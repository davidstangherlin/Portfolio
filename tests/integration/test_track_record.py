"""Scoring signals against made-up history (src/tracking/outcomes.py,
report.py): outcomes against the same-night average, dividends in total
return, scorecard selection (first of the month, action changes),
delisted companies, the monthly summary, 14-month deletion, and the
missed-opportunity rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src.models import Company, DailyPrice, DividendPayment, SignalSnapshot
from src.portfolio.holdings import add_parcel
from src.tracking import outcomes, report

pytestmark = pytest.mark.integration

START, END = date(2025, 9, 1), date(2026, 10, 2)
D = Decimal


def _weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _company(session, code, price_fn, action_fn, last_day=END, dividends=()):
    co = Company(ticker=f"{code}.AX", company_name=f"{code} Ltd", asx_code=code, sector="Industrials")
    session.add(co)
    session.flush()
    for i, d in enumerate(_weekdays(START, last_day)):
        price = D(str(round(price_fn(i), 4)))
        session.add(DailyPrice(company_id=co.company_id, price_date=d, close_price=price))
        session.add(SignalSnapshot(
            company_id=co.company_id, snapshot_date=d, price=price, action=action_fn(d), held=False,
            valuation_status="Undervalued", margin_of_safety_percent=D("30"), estimated_value=price * 2,
            score_total=0, score_value=0, score_performance=0, score_health=0, score_dividend=0, score_momentum=0,
            mos_ok=True, roe_ok=True, de_ok=True, yield_ok=True, red_flags=[], rules_version="2026-10-05"))
    for ex_date, amount in dividends:
        session.add(DividendPayment(company_id=co.company_id, ex_date=ex_date, amount=D(amount), abnormal=False))
    return co


@pytest.fixture()
def history(db_session):
    up = _company(db_session, "UP", lambda i: 10 * 1.004 ** i, lambda d: "BUY")
    down = _company(db_session, "DOWN", lambda i: 10 * 0.997 ** i, lambda d: "AVOID")
    flat = _company(db_session, "FLAT", lambda i: 10, lambda d: "BUY" if d >= date(2026, 6, 1) else "WATCH",
                    dividends=[(date(2026, 3, 2), "1.00")])
    gone = _company(db_session, "GONE", lambda i: 10, lambda d: "WATCH", last_day=date(2026, 3, 31))
    db_session.commit()
    return {"UP": up, "DOWN": down, "FLAT": flat, "GONE": gone}


def _outcome(session, code, night, months):
    return session.execute(text("""
        SELECT o.* FROM signal_outcomes o JOIN companies c USING (company_id)
        WHERE c.asx_code = :code AND o.snapshot_date = :night AND o.horizon_months = :m
    """), {"code": code, "night": night, "m": months}).mappings().one_or_none()


def test_outcomes_against_the_same_night_average(history, db_session):
    written = outcomes.fill_outcomes(db_session)
    db_session.commit()
    assert written > 0 and outcomes.fill_outcomes(db_session) == 0  # nothing scored twice

    up = _outcome(db_session, "UP", START, 1)
    down = _outcome(db_session, "DOWN", START, 1)
    assert up["end_date"] == date(2025, 10, 1) and up["universe_size"] == 4
    assert up["total_return"] > 0 > down["total_return"]
    assert up["excess_return"] > 0 > down["excess_return"]
    returns = [_outcome(db_session, c, START, 1)["total_return"] for c in ("UP", "DOWN", "FLAT", "GONE")]
    assert abs(up["benchmark_return"] - sum(returns) / 4) < D("0.01")
    assert up["gap_closed"] is not None  # priced below its estimate


def test_dividends_count_in_total_return(history, db_session):
    outcomes.fill_outcomes(db_session)
    flat = _outcome(db_session, "FLAT", date(2026, 1, 1), 3)  # 1 Jan: first weekday of January
    assert flat["dividends"] == D("1.0000") and flat["total_return"] == D("10.00")  # $10 flat + $1 dividend


def test_scorecard_is_monthly_firsts_plus_action_changes(history, db_session):
    outcomes.fill_outcomes(db_session)
    rows = db_session.execute(text("""
        SELECT o.snapshot_date, o.is_cohort, o.is_change FROM signal_outcomes o JOIN companies c USING (company_id)
        WHERE c.asx_code = 'FLAT' AND o.horizon_months = 1 ORDER BY 1
    """)).all()
    assert all(r.snapshot_date.day <= 3 or r.is_change for r in rows)  # first weekday of each month, or a change
    assert (date(2026, 6, 1), True, True) in [tuple(r) for r in rows]   # 1 June: both the month's first and the change
    assert _outcome(db_session, "FLAT", date(2026, 6, 2), 1) is None     # an ordinary day isn't scored


def test_a_company_that_stops_trading_is_scored_at_its_last_price(history, db_session):
    outcomes.fill_outcomes(db_session)
    gone = _outcome(db_session, "GONE", date(2026, 3, 2), 3)
    assert gone["delisted"] is True and gone["end_date"] == date(2026, 3, 31)
    assert _outcome(db_session, "GONE", START, 1)["delisted"] is False


def test_monthly_summary_and_deletion_after_14_months(history, db_session):
    outcomes.update_track_record(db_session, date(2026, 10, 5))
    db_session.commit()
    sept = db_session.execute(text("""
        SELECT signals, beat_benchmark FROM track_record_monthly
        WHERE month = '2025-09-01' AND action = 'BUY' AND horizon_months = 1
    """)).one()
    assert tuple(sept) == (1, 1)  # one monthly BUY signal (UP), which beat the average
    assert outcomes.retention_cutoff(date(2026, 10, 5)) == date(2025, 8, 1)

    run = outcomes.update_track_record(db_session, date(2026, 11, 20))  # cutoff moves to 1 Sep 2025... still kept
    assert run.pruned == 0
    run = outcomes.update_track_record(db_session, date(2026, 12, 5))   # cutoff 1 Oct 2025: September goes
    db_session.commit()
    assert run.pruned == 4 * 22  # four companies x 22 weekdays in September 2025
    left = db_session.execute(text("SELECT MIN(snapshot_date) FROM signal_snapshots")).scalar_one()
    assert left == date(2025, 10, 1)
    assert db_session.execute(text("SELECT COUNT(*) FROM track_record_monthly WHERE month = '2025-09-01'")).scalar_one() > 0


def test_verdict_and_order_check(history, db_session):
    outcomes.update_track_record(db_session, date(2026, 10, 5))
    db_session.commit()
    v = report.verdict(db_session, None)
    buy = next(a for a in v[1]["actions"] if a["action"] == "BUY")
    assert buy["confidence"] == "too early" and buy["signals"] >= 13
    assert v[1]["order"]["status"] == "too early"
    assert report.verdict(db_session, "1999-01-01")[1]["actions"] == []  # rules-version filter


def test_confidence_and_order_rules():
    assert [report.confidence(n) for n in (0, 29, 30, 100, 101)] == ["too early", "too early", "moderate", "moderate", "solid"]
    def a(action, excess, n=50):
        return {"action": action, "avg_excess": D(excess), "confidence": report.confidence(n)}
    assert report.order_check([a("BUY", "3"), a("WATCH", "0"), a("AVOID", "-2")])["status"] == "in order"
    assert report.order_check([a("BUY", "-1"), a("WATCH", "0"), a("AVOID", "-2")])["status"] == "out of order"
    assert report.order_check([a("BUY", "3"), a("WATCH", "0", n=10), a("AVOID", "-2")])["status"] == "too early"


def test_missed_opportunities_skip_shares_you_bought_soon_after(history, db_session):
    outcomes.update_track_record(db_session, date(2026, 10, 5))
    db_session.commit()
    missed, saved = report.missed_and_saved(db_session, None, {}, D("20"), {})
    assert [m["asx_code"] for m in missed] == ["UP"] and missed[0]["snapshot_date"] == START
    assert [s["asx_code"] for s in saved] == ["DOWN"]

    add_parcel(db_session, "UP", D("10"), D("10"), START + timedelta(days=20))  # acted on the first call
    db_session.commit()
    missed, _ = report.missed_and_saved(db_session, None, {}, D("20"), {})
    assert missed[0]["asx_code"] == "UP" and missed[0]["snapshot_date"] > START  # the 1 Sep call is excluded


def test_track_record_api(history, db_session):
    outcomes.update_track_record(db_session, date(2026, 10, 5))
    db_session.commit()
    data = TestClient(gui.create_app()).get("/api/track-record").json()
    assert set(data["verdict"]) == {"1", "3", "6", "12"}
    assert data["versions"] == ["2026-10-05"] and data["proven"] == {"actions": ["BUY"], "proven": False, "horizon": None}
    assert data["missed"][0]["asx_code"] == "UP"
    assert TestClient(gui.create_app()).get("/api/track-record?version=2026-10-05").status_code == 200


def test_dashboard_headline_once_results_exist(history, db_session):
    from datetime import datetime

    assert report.headline(db_session) is None
    outcomes.update_track_record(db_session, date(2026, 10, 5))
    db_session.commit()
    data = gui.dashboard_payload(db_session, date(2026, 10, 5), datetime(2026, 10, 5, 9))
    assert data["tracking"]["headline"]["action"] == "BUY" and data["tracking"]["headline"]["horizon_months"] == 3


def _snap(session, company, d, action, price, held=False):
    session.add(SignalSnapshot(
        company_id=company.company_id, snapshot_date=d, price=D(price), action=action, held=held,
        valuation_status="Undervalued", margin_of_safety_percent=D("30"), estimated_value=D(price) * 2,
        score_total=0, score_value=0, score_performance=0, score_health=0, score_dividend=0, score_momentum=0,
        mos_ok=True, roe_ok=True, de_ok=True, yield_ok=True, red_flags=[], rules_version="2026-10-05"))


def test_still_actionable_groups_by_freshness(db_session):
    latest = date(2026, 10, 2)
    cos = {}
    for code in ("NEW", "OPEN", "ROSE", "BOUGHT", "CUT", "BLIP"):
        cos[code] = Company(ticker=f"{code}.AX", company_name=f"{code} Ltd", asx_code=code)
        db_session.add(cos[code])
    db_session.flush()
    for d in _weekdays(latest - timedelta(days=60), latest):
        _snap(db_session, cos["NEW"], d, "BUY" if d >= latest - timedelta(days=3) else "WATCH", "10")
        _snap(db_session, cos["OPEN"], d, "BUY", "10")
        _snap(db_session, cos["ROSE"], d, "BUY" if d < latest - timedelta(days=20) else "WATCH", "10")
        _snap(db_session, cos["BOUGHT"], d, "BUY" if d < latest - timedelta(days=20) else "ACCUMULATE", "10",
              held=d >= latest - timedelta(days=20))
        _snap(db_session, cos["CUT"], d, "BUY", "10")
        _snap(db_session, cos["BLIP"], d, "BUY" if d < latest - timedelta(days=20) else "WATCH", "10")
    db_session.commit()

    def row(code, action, mos, price="10", held=None):
        return {"asx_code": code, "company_name": f"{code} Ltd", "action": action, "current_price": D(price),
                "margin_of_safety_percent": None if mos is None else D(mos), "held": held}
    current = [row("NEW", "BUY", "40"), row("OPEN", "BUY", "35"), row("ROSE", "WATCH", "10", price="14"),
               row("BOUGHT", "ACCUMULATE", "30", held=D("100")), row("CUT", "BUY", "15"), row("BLIP", "WATCH", "30")]
    out = report.actionable(db_session, current, ["BUY"], D("20"), {"OPEN": ["Ideas"]})

    assert [i["asx_code"] for i in out["new"]] == ["NEW"] and out["new"][0]["since"] == date(2026, 9, 29)
    assert [i["asx_code"] for i in out["open"]] == ["OPEN"] and out["open"][0]["watchlists"] == ["Ideas"]
    why = {i["asx_code"]: i["why"] for i in out["moved_on"]}
    assert why == {"ROSE": "price rose out of the buy zone", "BOUGHT": "you bought it",
                   "CUT": "estimated value fell", "BLIP": "now WATCH"}


def test_proven_actions_need_moderate_confidence_and_a_positive_result():
    def v(buy_signals, buy_excess):
        actions = [{"action": "BUY", "confidence": report.confidence(buy_signals), "avg_excess": D(buy_excess)},
                   {"action": "WATCH", "confidence": "solid", "avg_excess": D("9")}]  # not buy-side: never proven
        return {1: {"actions": actions}, 3: {"actions": actions}}
    assert report.proven_actions(v(40, "2")) == (["BUY"], True, 3)
    assert report.proven_actions(v(40, "-2")) == (["BUY"], False, None)
    assert report.proven_actions(v(10, "5")) == (["BUY"], False, None)


def test_nightly_commands(history, db_session, caplog):
    import logging

    from src.tracking import record_signals, score_signals

    caplog.set_level(logging.INFO)
    assert record_signals.main() == 0  # no valued companies in this history: records nothing, still succeeds
    assert score_signals.main() == 0
    assert "Scored" in caplog.text and "monthly summary rows refreshed" in caplog.text
    assert db_session.execute(text("SELECT COUNT(*) FROM signal_outcomes")).scalar_one() > 0
    assert score_signals.main() == 0  # a second run scores nothing twice
    assert "Scored 0 outcomes" in caplog.text
