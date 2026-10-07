"""Checking each ETF's returns against the ASX report and its own price
history (docs/AS_BUILT.md §26.1): a figure that doesn't agree is marked,
left off the chart and out of the category average."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from src.etf.performance import History, price_jump, report_checks
from src.etf.views import category_averages, report_flags


def steady(start: date, end: date, daily: float = 0.0004, jump_on: date | None = None, jump: float = 1.0) -> History:
    """Weekday closes growing steadily, optionally stepping by `jump` on one day."""
    dates, closes, d, p = [], [], start, 10.0
    while d <= end:
        if d.weekday() < 5:
            p *= 1 + daily
            if jump_on and d == jump_on:
                p *= jump
            dates.append(d)
            closes.append(p)
        d += timedelta(days=1)
    return History(dates, closes, [])


def test_a_one_day_step_beyond_40_percent_is_a_data_fault():
    assert price_jump(steady(date(2020, 1, 1), date(2026, 9, 30))) is None
    h = steady(date(2015, 1, 1), date(2026, 9, 30), jump_on=date(2022, 12, 5), jump=1 / 15)  # an unadjusted 15:1 split
    day, pct = price_jump(h)
    assert day == date(2022, 12, 5) and pct < Decimal("-90")
    assert price_jump(steady(date(2020, 1, 1), date(2026, 9, 30), jump_on=date(2024, 3, 4), jump=0.7)) is None  # -30%: possible


def _report(**returns):
    base = {f"return_{k}": None for k in ("1m", "3m", "6m", "1y", "3y", "5y", "10y", "since_inception")}
    return SimpleNamespace(report_month=date(2026, 7, 1), listing_date=None, **(base | returns))


def test_every_period_is_measured_to_the_reports_month_end():
    h = steady(date(2014, 1, 1), date(2026, 10, 6))
    checks = report_checks(h, _report(return_1m=Decimal("0.9"), return_1y=Decimal("10.6"), return_10y=Decimal("10.6")))
    assert set(checks) == {"return_1m", "return_1y", "return_10y"}
    ours, theirs = checks["return_1y"]
    assert abs(ours - 10.6) < 1 and theirs == 10.6
    # Since first price only when Sift's prices start near the listing date.
    assert "return_since_inception" not in report_checks(h, _report(return_since_inception=Decimal("10")))
    near = _report(return_since_inception=Decimal("10"))
    near.listing_date = date(2013, 12, 20)
    assert "return_since_inception" in report_checks(h, near)


def _row(**kw):
    return {"category": "Equity - Global", "check_month": date(2026, 7, 1), "report_checks": None,
            "price_jump_date": None, "price_jump_percent": None, "first_price_date": date(2015, 1, 2),
            "as_of_date": date(2026, 10, 2), "return_1y": Decimal("18"), "return_3y": Decimal("20"),
            "return_10y": Decimal("16"), "return_since_inception": Decimal("-3")} | kw


def test_a_gap_to_the_asx_figure_is_flagged_with_the_reason():
    flags = report_flags(_row(report_checks={"return_1y": [18.1, 18.4], "return_3y": [20.0, 24.5]}))
    assert list(flags) == ["return_3y"]
    assert flags["return_3y"] == "to the end of July 2026 Sift has +20.0%, the ASX report +24.5%"


def test_franking_credits_explain_a_shortfall_for_australian_equity_funds():
    checks = {"return_1y": [10.0, 13.5]}
    assert report_flags(_row(category="Equity - Australia", report_checks=checks)) == {}
    assert list(report_flags(_row(category="Equity - Global", report_checks=checks))) == ["return_1y"]
    assert list(report_flags(_row(category="Equity - Australia", report_checks={"return_1y": [15.0, 12.0]}))) == ["return_1y"]


def test_a_price_jump_flags_every_period_that_spans_it():
    flags = report_flags(_row(price_jump_date=date(2017, 3, 1), price_jump_percent=Decimal("-93.3")))
    assert set(flags) == {"return_10y", "return_since_inception"}  # 1, 3 and 5 years start after it
    assert "jumps -93.3% on 1 Mar 2017" in flags["return_10y"]


def test_flagged_figures_stay_out_of_the_category_average():
    rows = [{"category": "Equity - Global", "return_1y": Decimal("10"), "report_flags": {}},
            {"category": "Equity - Global", "return_1y": Decimal("-60"), "report_flags": {"return_1y": "jump"}}]
    avg = category_averages(rows)["Equity - Global"]
    assert avg["return_1y"] == Decimal("10.00") and avg["return_1y_n"] == 1


def _fund(code, category="Equity - Global", r1y=None, fum=1, flags=None, kind="ETF"):
    return {"asx_code": code, "category": category, "return_1y": r1y, "fum_aud": Decimal(fum), "security_type": kind,
            "report_flags": flags or {}}


def test_rank_and_median_within_the_category():
    from src.etf.views import peer_ranks
    rows = [_fund("NDQ", r1y=Decimal("18")), _fund("VGS", r1y=Decimal("12")), _fund("HACK", r1y=Decimal("40")),
            _fund("BAD", r1y=Decimal("-60"), flags={"return_1y": "jump"}), _fund("NEW"), _fund("VAS", "Equity - Australia", Decimal("50"))]
    p = peer_ranks(rows[0], rows)["return_1y"]
    assert (p["rank"], p["of"], p["ordinal"], p["median"]) == (2, 3, "2nd", Decimal("18.00"))  # BAD flagged, NEW blank, VAS elsewhere
    assert peer_ranks(rows[4], rows)["return_1y"]["rank"] is None                            # no figure of its own
    assert "return_since_inception" not in peer_ranks(rows[0], rows)


def test_the_default_comparison_is_the_broad_low_cost_fund():
    from src.etf.views import default_reference
    rows = [_fund("NDQ", fum=9), _fund("IVV", fum=14), _fund("VGS", fum=12), _fund("HACK", "Equity - Global Sectors", fum=1),
            _fund("VAS", "Equity - Australia", fum=20), _fund("A200", "Equity - Australia", fum=6),
            _fund("XYZ", "Crypto Assets", fum=1), _fund("ABC", "Crypto Assets", fum=2)]
    by = {r["asx_code"]: r for r in rows}
    assert default_reference(by["NDQ"], rows)["asx_code"] == "VGS"     # not IVV, the category's largest
    assert default_reference(by["HACK"], rows)["asx_code"] == "VGS"    # across categories
    assert default_reference(by["VGS"], rows)["asx_code"] == "IVV"     # never itself
    assert default_reference(by["VAS"], rows)["asx_code"] == "A200"
    assert default_reference(by["XYZ"], rows)["asx_code"] == "ABC"     # no preference: the category's largest
