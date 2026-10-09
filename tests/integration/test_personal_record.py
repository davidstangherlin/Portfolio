"""Multi-user Phase 2 (docs/AS_BUILT.md §34): the nightly record is Sift's
shared call for someone not holding each share, plus each person's call
on their own holdings; what changed, what was missed and the calls that
saved money are each person's own; history from before Phase 2 moves to
the first admin."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from src import accounts
from src.apply_schema import apply_schema
from src.config import get_engine
from src.models import SignalSnapshot
from src.portfolio.holdings import add_parcel
from src.tracking import outcomes, report
from src.tracking.signals import person_nights, record_signals, signal_changes
from tests.integration.test_screener import TODAY
from tests.integration.test_track_record import _company, _outcome, _snap, _weekdays
from tests.integration.test_tracking import _seed

pytestmark = pytest.mark.integration

D = Decimal


@pytest.fixture()
def sam(db_session):
    user = accounts.create_user(db_session, "sam@example.com", "Sam")
    db_session.commit()
    return user


def _personal(session, owner_id=None):
    sql = "SELECT c.asx_code, p.action, p.units, p.owner_id FROM position_snapshots p JOIN companies c USING (company_id)"
    return {(r.asx_code, r.owner_id): r for r in session.execute(text(sql))}


def test_the_shared_record_is_for_someone_not_holding_and_each_holder_gets_their_own(db_session, sam):
    good, dear = _seed(db_session)
    add_parcel(db_session, "GOOD", D("100"), D("8.00"), date(2025, 1, 15))  # the owner holds GOOD
    with accounts.acting_as(sam.user_id):
        add_parcel(db_session, "DEAR", D("5"), D("50.00"), date(2025, 1, 15))  # Sam holds DEAR
    db_session.commit()

    result = record_signals(db_session, TODAY)
    db_session.commit()
    shared = {s.company_id: s for s in db_session.query(SignalSnapshot)}
    assert (shared[good.company_id].action, shared[good.company_id].held) == ("BUY", False)  # nobody's holdings
    assert shared[dear.company_id].held is False

    owner = accounts.owner(db_session).user_id
    mine = _personal(db_session)
    assert result.personal == 2 and set(mine) == {("GOOD", owner), ("DEAR", sam.user_id)}
    assert mine[("GOOD", owner)].action == "ACCUMULATE" and mine[("GOOD", owner)].units == D("100")
    assert mine[("DEAR", sam.user_id)].action in ("HOLD", "REVIEW", "SELL")

    # Each person sees their own call laid over the shared one.
    assert {r["asx_code"]: (r["action"], r["held"]) for r in person_nights(db_session)}["GOOD"] == ("ACCUMULATE", True)
    with accounts.acting_as(sam.user_id):
        seen = {r["asx_code"]: (r["action"], r["held"]) for r in person_nights(db_session)}
    assert seen["GOOD"] == ("BUY", False) and seen["DEAR"][1] is True

    record_signals(db_session, TODAY)  # a second run the same night changes nothing
    assert len(_personal(db_session)) == 2


def _two_nights(session, code, shared, held=None, owner_id=None):
    """A company with shared calls on two nights and, optionally, someone's calls on it."""
    from src.models import Company
    co = Company(ticker=f"{code}.AX", company_name=f"{code} Ltd", asx_code=code)
    session.add(co)
    session.flush()
    nights = (date(2026, 10, 1), date(2026, 10, 2))
    for night, action in zip(nights, shared):
        _snap(session, co, night, action, "10")
    session.flush()
    for night, action in zip(nights, held or ()):
        session.execute(text("""INSERT INTO position_snapshots (owner_id, company_id, snapshot_date, units, action, rules_version)
                                VALUES (:o, :c, :d, 10, :a, '2026-10-05')"""),
                        {"o": owner_id, "c": co.company_id, "d": night, "a": action})
    return co


def test_what_changed_is_each_persons_own(db_session, sam):
    owner = accounts.owner(db_session).user_id
    _two_nights(db_session, "MKT", ("WATCH", "BUY"))                                      # shared move: everyone
    _two_nights(db_session, "MINE", ("BUY", "BUY"), ("ACCUMULATE", "SELL"), owner)        # owner's holding turned
    _two_nights(db_session, "SAMS", ("BUY", "AVOID"), ("HOLD", "HOLD"), sam.user_id)       # Sam's call didn't move
    db_session.commit()

    assert {c["asx_code"]: c["action"] for c in signal_changes(db_session)["changes"]} == {
        "MKT": "BUY", "MINE": "SELL", "SAMS": "AVOID"}
    with accounts.acting_as(sam.user_id):
        assert {c["asx_code"]: c["action"] for c in signal_changes(db_session)["changes"]} == {"MKT": "BUY"}


def test_held_calls_are_scored_and_saved_money_is_personal(db_session, sam):
    owner = accounts.owner(db_session).user_id
    # SLIDE falls steadily; Sift's shared call stays WATCH all along, so only the
    # owner's mid-month SELL makes 15 October a night worth scoring.
    slide = _company(db_session, "SLIDE", lambda i: 10 * 0.995 ** i, lambda d: "WATCH")
    _company(db_session, "UP", lambda i: 10 * 1.004 ** i, lambda d: "BUY")
    db_session.flush()
    sell_night = date(2025, 10, 15)
    for d in _weekdays(date(2025, 10, 1), date(2025, 10, 31)):
        db_session.execute(text("""INSERT INTO position_snapshots (owner_id, company_id, snapshot_date, units, action, rules_version)
                                   VALUES (:o, :c, :d, 10, :a, '2026-10-05')"""),
                           {"o": owner, "c": slide.company_id, "d": d, "a": "SELL" if d >= sell_night else "HOLD"})
    db_session.commit()

    outcomes.fill_outcomes(db_session)
    db_session.commit()
    assert _outcome(db_session, "SLIDE", sell_night, 6) is not None  # scored for the owner's call
    assert _outcome(db_session, "SLIDE", date(2025, 10, 14), 6) is None

    current = {}
    _, saved = report.missed_and_saved(db_session, None, current, D("20"), {})
    assert [(s["asx_code"], s["action"], s["snapshot_date"]) for s in saved] == [("SLIDE", "SELL", sell_night)]
    with accounts.acting_as(sam.user_id):
        _, saved = report.missed_and_saved(db_session, None, current, D("20"), {})
    assert saved == []  # Sam never held it; WATCH isn't a call that saves money


def test_history_from_before_phase_2_moves_to_the_first_admin(db_session, sam):
    owner = accounts.owner(db_session).user_id
    from src.models import Company
    co = Company(ticker="OLD.AX", company_name="OLD Ltd", asx_code="OLD")
    db_session.add(co)
    db_session.flush()
    _snap(db_session, co, date(2026, 10, 1), "ACCUMULATE", "10", held=True)  # recorded with the owner's holdings
    db_session.commit()

    apply_schema(get_engine())
    db_session.expire_all()
    assert set(_personal(db_session)) == {("OLD", owner)}
    assert [(r["action"], r["held"]) for r in person_nights(db_session)] == [("ACCUMULATE", True)]
    with accounts.acting_as(sam.user_id):
        assert person_nights(db_session) == []  # someone else's held call isn't Sam's
    db_session.rollback()  # end the read, so the schema can take its locks
    apply_schema(get_engine())  # idempotent
    assert len(_personal(db_session)) == 1
