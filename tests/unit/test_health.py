"""Piotroski F-Score and Altman Z-Score against worked examples
(src/analytics/health.py, docs/kb/features/financial-health.md)."""

import pytest

from src.analytics import health, rules


def report(year, **kw):
    base = {"fiscal_year": year, "revenue": 1000, "net_profit_after_tax": 100, "operating_cash_flow": 150,
            "total_assets": 2000, "total_liabilities": 800, "total_debt": 400, "current_assets": 600,
            "current_liabilities": 300, "gross_profit": 400, "shares_outstanding": 1000, "ebit": 160,
            "retained_earnings": 500, "eps": 0.1}
    return base | kw


def test_a_company_improving_on_every_count_scores_nine():
    now = report(2026, revenue=1200, net_profit_after_tax=130, total_debt=300, current_assets=700, gross_profit=500)
    f = health.piotroski([now, report(2025), report(2024)])
    assert (f["score"], f["checks_with_data"], f["level"]) == (9, 9, "STRONG")


def test_a_weakening_company_scores_low():
    now = report(2026, revenue=900, net_profit_after_tax=-20, operating_cash_flow=-30, total_debt=600,
                 current_assets=500, gross_profit=300, shares_outstanding=1200)
    f = health.piotroski([now, report(2025), report(2024)])
    assert f["score"] == 0 and f["level"] == "WEAK"
    assert {c["key"]: c["passed"] for c in f["checks"]}["no_new_shares"] is False


def test_missing_data_neither_passes_nor_fails():
    blank = dict(current_assets=None, current_liabilities=None, gross_profit=None, shares_outstanding=None, eps=None)
    f = health.piotroski([report(2026, **blank), report(2025, **blank)])
    assert f["checks_with_data"] == 6 and f["level"] != "NOT_ENOUGH"
    f = health.piotroski([report(2026, **blank, operating_cash_flow=None), report(2025, **blank)])
    assert f["checks_with_data"] == 4 and f["level"] == "NOT_ENOUGH"
    assert health.piotroski([report(2026)])["level"] == "NOT_ENOUGH"  # one year can't show change


def test_no_debt_either_year_counts_as_debt_not_rising():
    f = health.piotroski([report(2026, total_debt=0), report(2025, total_debt=0)])
    assert {c["key"]: c["passed"] for c in f["checks"]}["debt_down"] is True


def test_altman_zones():
    z = health.altman(report(2026), market_value=3000)
    expected = 1.2 * 300 / 2000 + 1.4 * 500 / 2000 + 3.3 * 160 / 2000 + 0.6 * 3000 / 800 + 1.0 * 1000 / 2000
    assert z["z"] == pytest.approx(expected) and z["zone"] == "SAFE"
    weak = health.altman(report(2026, retained_earnings=-900, ebit=-50, current_assets=200), market_value=100)
    assert weak["zone"] == "DISTRESS"
    assert health.caution_text(weak["z"], weak["zone"]).startswith("possible financial distress (Altman Z-Score")
    assert health.altman(report(2026, retained_earnings=None), 3000)["zone"] is None
    assert health.caution_text(2.5, "GREY") is None


def test_benjamini_hochberg_keeps_only_findings_that_survive():
    def t(p, mean=2.0):  # a test with this p-value, built through the real function
        import math
        from scipy.stats import t as tdist
        n, df = 100, 99
        tval = tdist.ppf(1 - p / 2, df)
        se = mean / tval
        sd = se * math.sqrt(n)
        return rules.test("BUY", 1, n, mean, (n - 1) * sd * sd + n * mean * mean)
    family = [t(0.001), t(0.02), t(0.03), t(0.2)]
    assert all(x["kind"] == "BEATING" for x in family[:3])   # each passes alone at 5%
    assert rules.adjust(family) == 4
    kinds = [x["kind"] for x in family]
    assert kinds == ["BEATING", "BEATING", "BEATING", "UNCLEAR"]  # 0.03 <= 3 x 5% / 4 survives; 0.2 does not
    assert family[0]["q_value"] == pytest.approx(0.004, rel=1e-3)
    for x in family:  # a bar clear of the average always means a finding
        assert (x["low"] > 0) == (x["kind"] == "BEATING")
    lone = [t(0.04)] + [t(0.6) for _ in range(9)]
    rules.adjust(lone)
    assert lone[0]["kind"] == "UNCLEAR" and lone[0]["p_value"] < 0.05   # 1 in 25 alone, but 1 of 10 tests
