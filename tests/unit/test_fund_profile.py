"""Reading Yahoo's fund data into a FundProfile (docs/AS_BUILT.md §26.3),
shaped as yfinance 1.x returns it. No network."""

from decimal import Decimal

import pandas as pd

from src.ingestion.yahoo_client import parse_fund_profile

TOP = pd.DataFrame({"Name": ["BHP Group Ltd", "Commonwealth Bank of Australia", " "],
                    "Holding Percent": [0.0912, 0.0855, 0.01]}, index=pd.Index(["BHP.AX", "CBA.AX", "X"], name="Symbol"))
BONDS = pd.DataFrame({"VAF.AX": [5.6, 7.2, None], "Category Average": [5, 6, None]},
                     index=pd.Index(["Duration", "Maturity", "Credit Quality"], name="Average"))


def test_an_equity_etf():
    p = parse_fund_profile("Vanguard Australian Shares Index ETF seeks to track the S&P/ASX 300.",
                           {"cashPosition": 0.003, "stockPosition": 0.997, "bondPosition": 0.0, "otherPosition": 0.0},
                           TOP, {"financial_services": 0.31, "basic_materials": 0.2, "technology": 0.0, "realestate": 0.07},
                           {}, pd.DataFrame())
    assert p.description.startswith("Vanguard") and p.stock_percent == Decimal("99.70") and p.cash_percent == Decimal("0.30")
    assert p.bond_percent is None and p.other_percent is None
    assert list(p.sector_weightings) == ["financial_services", "basic_materials", "realestate"]  # largest first, zeros gone
    assert p.sector_weightings["financial_services"] == 31.0
    assert [(h.rank, h.symbol, h.weight_percent) for h in p.holdings] == [(1, "BHP.AX", Decimal("9.12")), (2, "CBA.AX", Decimal("8.55"))]
    assert p.top10_percent == Decimal("17.67")


def test_a_bond_etf():
    p = parse_fund_profile(None, {"bondPosition": 0.98, "cashPosition": 0.02}, pd.DataFrame(), {},
                           {"aaa": 0.55, "aa": 0.3, "a": 0.1, "bbb": 0.05}, BONDS)
    assert p.bond_percent == Decimal("98.00") and p.duration_years == Decimal("5.6") and p.maturity_years == Decimal("7.2")
    assert p.bond_ratings == {"aaa": 55.0, "aa": 30.0, "a": 10.0, "bbb": 5.0}
    assert p.holdings == [] and p.top10_percent is None and p.sector_weightings is None


def test_percent_figures_are_not_scaled_twice():
    p = parse_fund_profile("x", {}, None, {"technology": 45.0, "healthcare": 20.0}, None, None)
    assert p.sector_weightings == {"technology": 45.0, "healthcare": 20.0}
