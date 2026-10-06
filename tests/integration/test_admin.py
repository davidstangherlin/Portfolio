"""The admin console against a real database: a scenario with no changes
reproduces live exactly, changes move the results as they should, the
workings equal the engine's figures, and the API keeps the usual guards."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import gui
from src.admin import scenarios, workings
from src.portfolio.holdings import add_parcel, position_summaries
from src.screening.enriched import load_universe
from src.settings import LIVE, with_overrides
from src.valuation.engine import compute_metrics
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 6)
WRITE = {"X-Sift": "1"}
KB = {e["id"] for e in json.loads((Path(__file__).resolve().parents[2] / "web/knowledge.json").read_text())["entries"]}


@pytest.fixture()
def seeded(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    _seed_and_value(db_session, "BANK", "Financial Services", Decimal("110000000"), Decimal("0.90"), Decimal("12.00"))
    add_parcel(db_session, "GOOD", Decimal("100"), Decimal("8.00"), date(2025, 1, 15))
    db_session.commit()
    scenarios._cache.update(key=None, inputs=[])
    return db_session


def test_no_changes_reproduces_live_exactly(seeded):
    stored = {r["asx_code"]: r for r in load_universe(seeded, TODAY).rows}
    live = scenarios.evaluate(scenarios.prepare(seeded), LIVE, position_summaries(seeded, TODAY), TODAY)
    assert set(live) == set(stored) == {"GOOD", "DEAR", "BANK"}
    for code, row in stored.items():
        for key in ("action", "action_reason", "margin_of_safety_percent", "dcf_intrinsic_value", "mos_ok", "roe_ok",
                    "de_ok", "yield_ok", "valuation_status", "axis_scores", "price_signal", "earnings_quality"):
            assert live[code][key] == row[key], (code, key)
    result = scenarios.run(seeded, LIVE, TODAY, {})
    assert result["changes"] == [] and result["changed"] == [] and result["moves"] == []


def test_a_stricter_test_moves_the_actions(seeded):
    result = scenarios.run(seeded, with_overrides({"min_margin_of_safety": "85", "score_mos_strong": "90"}), TODAY, {"DEAR": ["Ideas"]})
    assert [c["key"] for c in result["changes"]] == ["min_margin_of_safety", "score_mos_strong"]
    good = next(c for c in result["changed"] if c["asx_code"] == "GOOD")
    assert (good["live_action"], good["action"], good["held"]) == ("ACCUMULATE", "HOLD", True)
    assert {m["asx_code"] for m in result["mine"]} == {"GOOD", "DEAR"}  # held, and watched
    assert sum(b["live"] for b in result["distribution"]) == sum(b["scenario"] for b in result["distribution"])


def test_a_valuation_change_matches_the_engine(seeded):
    s = with_overrides({"discount_rate": "11", "dcf_growth_rate": "5", "fcf_average_years": "1"})
    rows = scenarios.evaluate(scenarios.prepare(seeded), s, {}, TODAY)
    p = next(x for x in scenarios.prepare(seeded) if x.asx_code == "GOOD")
    direct = compute_metrics(scenarios.with_average_years(p.inputs, 1), settings=s)["dcf_intrinsic_value"]
    assert rows["GOOD"]["dcf_intrinsic_value"] == direct.quantize(Decimal("0.0001"))
    live = scenarios.evaluate(scenarios.prepare(seeded), LIVE, {}, TODAY)
    assert rows["GOOD"]["dcf_intrinsic_value"] < live["GOOD"]["dcf_intrinsic_value"]
    assert rows["BANK"]["valuation_method"] == "DDM"


def test_inputs_are_gathered_once_per_data_version(seeded):
    first = scenarios.prepare(seeded)
    assert scenarios.prepare(seeded) is first
    seeded.execute(gui.text("UPDATE financial_reports SET revenue = revenue + 1 WHERE fiscal_year = 2026"))
    seeded.execute(gui.text("INSERT INTO financial_reports (company_id, fiscal_year, period_type, report_date) "
                            "SELECT company_id, 2020, 'FY', '2020-06-30' FROM companies WHERE asx_code = 'DEAR'"))
    seeded.commit()
    assert scenarios.prepare(seeded) is not first


@pytest.mark.parametrize("code", ["GOOD", "BANK"])
def test_workings_equal_the_engine(seeded, code):
    w = workings.company_workings(seeded, code, TODAY)
    p = next(x for x in scenarios.prepare(seeded) if x.asx_code == code)
    m = compute_metrics(scenarios.with_average_years(p.inputs, LIVE.fcf_average_years))
    assert w["estimated_value"] == m["dcf_intrinsic_value"]
    assert w["valuation"]["estimated_value"] == m["dcf_intrinsic_value"]  # the step-by-step arithmetic lands on the same figure
    assert w["valuation"]["method"] == ("DDM" if code == "BANK" else "DCF")
    assert [r["result"] for r in w["ratios"] if r["title"] == "ROE"] == [m["roe"]]
    current = [c for row in w["sensitivity"]["rows"] for c in row["cells"] if c and c["current"]]
    assert len(current) == 1 and current[0]["value"] == m["dcf_intrinsic_value"]
    ids = {w["valuation"]["help_id"], w["action"]["help_id"], w["score"]["help_id"]}
    ids |= {s["help_id"] for group in (w["valuation"]["steps"], w["ratios"], w["markers"], w["tests"]) for s in group}
    assert ids <= KB, ids - KB


def test_admin_api(seeded):
    client = TestClient(gui.create_app())
    settings = client.get("/api/admin/settings").json()
    assert len(settings["settings"]) == 29 and settings["settings"][2]["live"] == 9.0  # discount rate shown as 9%
    assert client.post("/api/admin/scenarios", json={"name": "x"}).status_code == 403  # no X-Sift header
    bad = client.post("/api/admin/scenarios", json={"name": "Odd", "overrides": {"discount_rate": "2"}}, headers=WRITE)
    assert bad.status_code == 400 and "between 3 and 25" in bad.json()["detail"]
    sc = client.post("/api/admin/scenarios", headers=WRITE,
                     json={"name": "Cautious", "notes": "test", "overrides": {"discount_rate": "10.5", "min_roe": "12"}}).json()
    assert sc["overrides"] == {"discount_rate": "10.5"} and sc["changes"] == 1  # an unchanged value isn't kept
    assert client.post("/api/admin/scenarios", json={"name": "cautious"}, headers=WRITE).status_code == 400  # name taken
    base = f"/api/admin/scenarios/{sc['scenario_id']}"
    assert client.put(base, json={"name": "Careful", "overrides": {"dcf_growth_rate": "6"}}, headers=WRITE).json()["name"] == "Careful"
    assert [x["name"] for x in client.get("/api/admin/scenarios").json()["scenarios"]] == ["Careful"]
    run = client.post("/api/admin/run", json={"overrides": {"dcf_growth_rate": "6"}}, headers=WRITE)
    assert run.status_code == 200 and run.json()["changes"][0]["scenario"] == 6.0
    assert client.post("/api/admin/run", json={"overrides": {"terminal_growth_rate": "5", "discount_rate": "4"}},
                       headers=WRITE).status_code == 400
    live_w = client.get("/api/company/GOOD/workings").json()
    scen_w = client.get(f"/api/company/GOOD/workings?scenario={sc['scenario_id']}").json()
    assert scen_w["scenario"] == "Careful" and scen_w["estimated_value"] < live_w["estimated_value"]
    assert client.get("/api/company/NOPE/workings").status_code == 404
    assert client.delete(base, headers=WRITE).json() == {"deleted": "Careful"}
    assert client.get(base).status_code == 404
