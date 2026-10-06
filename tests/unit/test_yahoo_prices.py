"""YahooClient.get_price_history(): closes as traded (not scaled down for
later dividends), with splits and distributions from the same request
(docs/AS_BUILT.md §25)."""

from datetime import date
from decimal import Decimal

import pandas as pd

from src.ingestion import yahoo_client


class FakeTicker:
    def __init__(self, symbol):
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        index = pd.DatetimeIndex(["2026-09-01", "2026-09-02", "2026-09-03"])
        return pd.DataFrame({"Close": [100.0, 98.5, 99.0], "Adj Close": [97.0, 98.5, 99.0],
                             "Volume": [1000, 2000, float("nan")], "Dividends": [0.0, 1.5, 0.0],
                             "Stock Splits": [0.0, 0.0, 2.0]}, index=index)

    def get_info(self):
        return {"sharesOutstanding": 10}


def test_closes_are_as_traded_with_actions(monkeypatch):
    monkeypatch.setattr(yahoo_client.yf, "Ticker", FakeTicker)
    client = yahoo_client.YahooClient("vas")
    bars = client.get_price_history("1mo")
    assert client._ticker.calls == [{"period": "1mo", "interval": "1d", "auto_adjust": False, "actions": True}]
    assert [b.close_price for b in bars] == [Decimal("100.0"), Decimal("98.5"), Decimal("99.0")]  # not Adj Close
    assert bars[0].market_cap == Decimal("1000.0") and bars[2].volume is None
    assert [(p.ex_date, p.amount) for p in client.last_dividends] == [(date(2026, 9, 2), Decimal("1.5"))]
    assert client.last_splits == [(date(2026, 9, 3), Decimal("2.0"))]


def test_market_cap_lookup_can_be_skipped(monkeypatch):
    monkeypatch.setattr(yahoo_client.yf, "Ticker", FakeTicker)
    bars = yahoo_client.YahooClient("VAS").get_price_history("1mo", include_market_cap=False)
    assert all(b.market_cap is None for b in bars)
