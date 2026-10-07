"""Exchange rates for currencies Yahoo has no direct pair for (known
issue #36: the Papua New Guinea kina, used by BFL, KSL and SST)."""

from datetime import date
from decimal import Decimal

from src.ingestion.currency import cross_rates, invert
from src.ingestion.yahoo_client import YahooClient

D1, D2 = date(2025, 12, 30), date(2025, 12, 31)


def test_invert_and_chain():
    assert invert([(D1, Decimal("4"))]) == [(D1, Decimal("0.2500000000"))]
    pgk_usd = [(D1, Decimal("0.25")), (D2, Decimal("0.26"))]
    usd_aud = [(D1, Decimal("1.5"))]                       # nothing yet for D2: D1's rate carries over
    assert cross_rates(pgk_usd, usd_aud) == [(D1, Decimal("0.375")), (D2, Decimal("0.390"))]
    assert cross_rates(pgk_usd, []) == []


def _symbols(monkeypatch, available):
    asked = []

    def fake(pair, start, end):
        asked.append(pair)
        return available.get(pair, [])
    monkeypatch.setattr(YahooClient, "_fx_closes", staticmethod(fake))
    return asked


def test_kina_is_chained_through_the_us_dollar(monkeypatch):
    # Yahoo quotes the kina only as PGK=X (kina per US dollar).
    asked = _symbols(monkeypatch, {"PGK=X": [(D2, Decimal("4"))], "USDAUD=X": [(D2, Decimal("1.5"))]})
    rates = YahooClient.get_fx_history("PGK", "AUD", D1, D2)
    assert rates == [(D2, Decimal("0.3750000000"))]                 # 1/4 x 1.5
    assert asked == ["PGKAUD=X", "PGKUSD=X", "USDPGK=X", "PGK=X", "USDAUD=X"]


def test_a_direct_pair_is_used_when_yahoo_has_one(monkeypatch):
    asked = _symbols(monkeypatch, {"USDAUD=X": [(D2, Decimal("1.5"))]})
    assert YahooClient.get_fx_history("USD", "AUD", D1, D2) == [(D2, Decimal("1.5"))]
    assert asked == ["USDAUD=X"]


def test_no_route_means_no_rate(monkeypatch):
    _symbols(monkeypatch, {"USDAUD=X": [(D2, Decimal("1.5"))]})
    assert YahooClient.get_fx_history("XYZ", "AUD", D1, D2) == []
