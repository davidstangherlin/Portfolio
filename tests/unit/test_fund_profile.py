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


def test_a_feeder_fund_is_looked_through():
    """The ASX's IVV holds 99.97% in the US IVV: its top 10 and sectors are
    the US fund's, scaled by that share; its own description and mix stay."""
    from src.ingestion.yahoo_client import FundHolding, FundProfile, look_through
    feeder = FundProfile("iShares S&P 500 ETF (ASX).", stock_percent=Decimal("99.7"), cash_percent=Decimal("0.3"),
                         holdings=[FundHolding(1, "IVV", "iShares Core S&P 500 ETF", Decimal("99.97"))])
    us = FundProfile("US fund.", sector_weightings={"technology": 33.0, "financial_services": 13.0},
                     holdings=[FundHolding(1, "NVDA", "NVIDIA Corp", Decimal("7.50")), FundHolding(2, "AAPL", "Apple Inc", Decimal("6.80"))])
    asked = []
    p = look_through(feeder, lambda s: asked.append(s) or us, "IVV.AX")
    assert asked == ["IVV"]
    assert [(h.symbol, h.weight_percent) for h in p.holdings] == [("NVDA", Decimal("7.50")), ("AAPL", Decimal("6.80"))]
    assert p.sector_weightings == {"technology": 33.0, "financial_services": 13.0}
    assert (p.look_through_symbol, p.look_through_percent) == ("IVV", Decimal("99.97"))
    assert p.description == "iShares S&P 500 ETF (ASX)." and p.stock_percent == Decimal("99.7")
    assert p.top10_percent == Decimal("14.30")


def test_an_ordinary_fund_or_a_failed_look_is_left_alone():
    from src.ingestion.yahoo_client import FundHolding, FundProfile, look_through
    broad = FundProfile("x", holdings=[FundHolding(1, "BHP.AX", "BHP Group", Decimal("9.1"))])
    assert look_through(broad, lambda s: 1 / 0) is broad and broad.look_through_symbol is None   # never fetched
    feeder = FundProfile("y", holdings=[FundHolding(1, "IOO", "iShares Global 100 ETF", Decimal("99.9"))])
    assert look_through(feeder, lambda s: None).holdings[0].symbol == "IOO"                       # Yahoo had nothing
    no_symbol = FundProfile("z", holdings=[FundHolding(1, None, "Some unit trust", Decimal("100"))])
    assert look_through(no_symbol, lambda s: 1 / 0).holdings[0].name == "Some unit trust"
