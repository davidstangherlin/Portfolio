"""Builds spreadsheets shaped like the ASX Investment Products report, for
the ETF tests (src/etf/asx_report.py). Two layouts, since the real one
isn't a published format: a title, a merged "Performance" group heading
over the period columns, fees as Excel percents and sizes in $m (layout
"grouped"); and a single heading row with whole-number percents and sizes
in dollars (layout "flat")."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

ETFS = [
    # code, name, issuer, type, exposure, benchmark, fee %, FUM $m, flows $m, spread %, 1m, 1y, 3y, 5y, 10y
    ("VAS", "Vanguard Australian Shares Index ETF", "Vanguard", "ETF", "Australian Equities", "S&P/ASX 300",
     0.07, 18500.5, 210.2, 0.02, 1.2, 12.5, 9.1, 8.4, 8.9),
    ("IOZ", "iShares Core S&P/ASX 200 ETF", "BlackRock", "ETF", "Australian Equities", "S&P/ASX 200",
     0.05, 6100.0, 55.0, 0.03, 1.1, 12.1, 8.9, 8.2, None),
    ("NDQ", "Betashares Nasdaq 100 ETF", "Betashares", "ETF", "Global Equities", "Nasdaq-100",
     0.48, 5200.0, -12.5, 0.05, -2.4, 24.3, 15.2, 17.8, None),
    ("HACK", "Betashares Global Cybersecurity ETF", "Betashares", "Active ETF", "Global Equities", None,
     0.67, 900.0, 3.0, 0.09, 3.3, 30.1, None, None, None),
    ("GOLD", "Global X Physical Gold", "Global X", "Structured Product", "Commodities", "Gold spot",
     0.40, 2500.0, 40.0, 0.06, 5.0, 35.0, 18.0, 12.0, 9.0),
]
LICS = [("AFI", "Australian Foundation Investment Co", "AFIC", "LIC", "Australian Equities")]


def build_report(folder: Path, name: str = "asx-investment-products-aug-2026.xlsx", layout: str = "grouped",
                 etfs=ETFS) -> Path:
    wb = Workbook()
    ws = wb.active
    if layout == "grouped":
        ws.title = "ETP Spotlight"
        ws.append(["ASX Investment Products - August 2026"])
        ws.append([])
        ws.append(["Fund details"] + [None] * 6 + ["Size and flows", None, None, "Performance (%)", None, None, None, None])
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=7)
        ws.merge_cells(start_row=3, start_column=8, end_row=3, end_column=10)
        ws.merge_cells(start_row=3, start_column=11, end_row=3, end_column=15)
        ws.append(["ASX Code", "Fund Name", "Issuer", "Type", "Exposure", "Benchmark", "Management Fee",
                   "FUM ($m)", "Net Flows ($m)", "Avg Bid/Ask Spread", "1 Month", "1 Year", "3 Year", "5 Year", "10 Year"])
        for e in etfs:
            ws.append(list(e[:6]) + [e[6] / 100, e[7], e[8], e[9] / 100] + list(e[10:]))
            row = ws.max_row
            for col in (7, 10):
                ws.cell(row=row, column=col).number_format = "0.00%"
        for code, name_, issuer, type_, exposure in LICS:
            ws.append([code, name_, issuer, type_, exposure])
        ws.append(["Total", None, None, None, None, None, None, sum(e[7] for e in etfs)])
        lic = wb.create_sheet("LIC Spotlight")
        lic.append(["ASX Code", "Name", "Manager", "Type"])
        lic.append(["ARG", "Argo Investments", "Argo", "LIC"])
    else:
        ws.title = "Exchange Traded Products"
        ws.append(["ASX code", "ETP name", "Product issuer", "Product type", "Asset class", "Index",
                   "MER (%)", "Funds under management", "1 Mth Return (%)", "1 Yr Return (%)", "5 Yr Return (%)",
                   "Since Inception (%)", "Listing date", "Distribution frequency"])
        for e in etfs:
            ws.append(list(e[:6]) + [e[6], e[7] * 1_000_000, e[10], e[11], e[13], 7.5, "2009-05-04", "Quarterly"])
    path = Path(folder) / name
    wb.save(path)
    return path


def build_asx_2026(folder: Path, name: str = "asx-investment-products-july-2026-abs.xlsx") -> Path:
    """The layout of the real report (July 2026): sheets named "Spotlight
    ...", the list starting in column B under seven blank rows, a title row,
    a group row (Activity, Prices, Returns), categories as section rows
    between the funds, "^" in column A for funds that hold other ETFs,
    returns, yields and spreads as plain fractions, MER as a percent, index
    rows and footnotes at the end, and LIC, A-REIT and infrastructure
    sheets in the same layout."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Spotlight ETPs"
    ws.append([])
    ws.append([None, "ETP Summary - July 2026"])
    lst = wb.create_sheet("Spotlight ETP List")
    for _ in range(7):
        lst.append([])
    lst.append([None, "Exchange Traded Product Summary - July 2026", None, None, None, "Transaction days: 23"])
    lst.append([None, "IRESS Watchlist: /ETFASX", None, None, None, "Activity", None, None, None, None, "Prices", "Returns"])
    lst.append([None, "ASX \nCode", "Type", "Issuer", "Fund Name", "  MER (% p.a)\n##", "FUM ($m)#", "FUM ($m) Change",
                "Funds Inflow / Outflow ($m) **", "Transacted Value ($)", "% Spread*", "Last ($)",
                "Historical Distribution Yield", "1 Month Total Return", "1 Year Total Return",
                "3 Year Total Return (ann.)", "5 Year Total Return (ann.)"])
    rows = [
        ("Equity - Australia", None),
        (None, ["VAS", "ETF", "Vanguard", "Vanguard Australian Shares Index ETF", 0.07, 26170.07, 300.1, 412.5, 900000000.5,
                0.000223, 110.5, 0.0293, 0.012, 0.0671, 0.091, 0.0906]),
        ("^", ["G200", "Complex", "Betashares", "Betashares Wealthbuilder Aus200 Geared Complex ETF", 0.35, 120.5, 3.1, 4.2,
               5000000, 0.0011, 12.3, 0.021, 0.03, 0.15, "n/a", "n/a"]),
        ("Equity - Global", None),
        (None, ["NDQ", "ETF", "Betashares", "Betashares Nasdaq 100 ETF", 0.48, 8714.88, 50.0, 60.0, 300000000,
                0.000326, 50.1, 0.0153, 0.02, 0.1071, 0.21, 0.1519]),
        (None, ["HACK", "Active", "Betashares", "Betashares Global Cybersecurity ETF", 0.67, 900.0, 1.0, 2.0, 1000000,
                0.0009, 14.0, 0.005, -0.01, 1.1512, 0.25, 0.18]),
        ("Commodity ", None),
        (None, ["GOLD", "SP", "Global X", "Global X Physical Gold", 0.4, 5476.49, 10.0, 20.0, 80000000,
                0.000387, 40.0, 0, 0.04, 0.1327, 0.15, 0.1809]),
        ("Australian Indices", None),
        (None, ["XJO", "Index", "S&P/ASX 200", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", 0.01, 0.06, 0.09, 0.08]),
    ]
    for mark, row in rows:
        if row is None:
            lst.append([None, mark])
        else:
            lst.append([mark] + row)
    lst.append([])
    lst.append([None, "Type: ETF = Exchange Transacted Fund, SP = Structured Product"])
    lst.append([None, "^  Identifies an ETF that invests in whole or in part into another ETF admitted to ASX."])
    for title in ("Spotlight LIC List", "Spotlight A-REITS  List", "Spotlight Infra  List"):
        other = wb.create_sheet(title)
        for _ in range(9):
            other.append([])
        other.append([None, "ASX \nCode", "Type", "Fund Name", "Mkt Cap ($m)"])
        other.append([None, "Equity - Australia"])
        other.append([None, "AFI", "Shares", "Australian Foundation Investment Company", 8421.43])
    path = Path(folder) / name
    wb.save(path)
    return path
