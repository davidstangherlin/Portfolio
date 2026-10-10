"""Reading brokers' exports (src/portfolio/importer.py): dates, codes,
numbers and sides as brokers write them, the heading row, the columns and
which broker a file came from."""

from datetime import date
from decimal import Decimal

import pytest

from src.portfolio import importer as im


@pytest.mark.parametrize("raw, want", [
    ("03/10/2026", date(2026, 10, 3)), ("3/10/26", date(2026, 10, 3)), ("2026-10-03", date(2026, 10, 3)),
    ("2026-10-03 14:22:01", date(2026, 10, 3)), ("2026-10-03T14:22:01", date(2026, 10, 3)), ("3 Oct 2026", date(2026, 10, 3)),
    ("Oct 3, 2026 10:01:02 AEDT", date(2026, 10, 3)), ("03-Oct-2026", date(2026, 10, 3)), ("20261003", date(2026, 10, 3)),
    ("", None), ("soon", None),
])
def test_dates_as_brokers_write_them(raw, want):
    assert im.parse_when(raw) == want


def test_codes_numbers_and_sides():
    assert im.clean_code("BHP.AX") == ("BHP", None) and im.clean_code("ASX:CBA") == ("CBA", None)
    assert im.clean_code("AAPL.US") == ("AAPL", "US") and im.clean_code("bhp") == ("BHP", None) and im.clean_code("") == (None, None)
    assert im.number("$1,234.50") == Decimal("1234.50") and im.number("(19.95)") == Decimal("-19.95") and im.number("-") is None
    assert [im.side_of(x) for x in ("B", "Buy", "BOUGHT", "s", "Sell", "Dividend")] == ["BUY", "BUY", "BUY", "SELL", "SELL", None]


def test_heading_row_columns_and_broker():
    rows = [["Account 123456"], ["Report run 3/10/2026"], ["Trade date", "Instrument code", "Market code", "Quantity", "Price",
                                                             "Transaction type", "Transaction fee", "Currency"]]
    assert im.find_header(rows) == 2
    m = im.guess_mapping(rows[2])
    assert (m["date"], m["code"], m["market"], m["units"], m["price"], m["side"], m["brokerage"], m["currency"]) == (0, 1, 2, 3, 4, 5, 6, 7)
    assert im.detect_broker(rows[2]) == "sharesies"
    assert im.detect_broker(["Date", "Reference", "Details", "Debit($)", "Credit($)", "Balance($)"]) == "commsec"
    assert im.find_header([["a", "b"], ["1", "2"]]) == 0  # nothing recognised: the person chooses the columns


def test_interactive_brokers_statement_keeps_its_trades():
    rows = [["Statement", "Header", "Field Name", "Field Value"], ["Statement", "Data", "Period", "2026"],
            ["Trades", "Header", "DataDiscriminator", "Symbol", "Date/Time", "Quantity", "T. Price", "Comm/Fee", "Currency"],
            ["Trades", "Data", "Order", "BHP", "2026-03-02, 10:01:00", "100", "45.10", "-6", "AUD"],
            ["Trades", "Data", "Total", "", "", "", "", "", ""]]
    out = im._ibkr_trades(rows)
    assert out[0][1] == "Symbol" and len(out) == 2 and out[1][1] == "BHP"
