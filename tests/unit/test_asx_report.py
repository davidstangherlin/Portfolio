"""Reading the ASX Investment Products report (src/etf/asx_report.py), from
spreadsheets built in two plausible layouts (tests/unit/_etf_report.py),
since the real layout isn't a published format."""

from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook

from src.etf import asx_report
from src.etf.asx_report import ReportError, match_field, month_from_name, read_report, report_links
from tests.unit._etf_report import build_asx_2026, build_report


@pytest.mark.parametrize("name,expected", [
    ("asx-investment-products-aug-2026.xlsx", date(2026, 8, 1)),
    ("asx-investment-products-december-2025-abs.xlsx", date(2025, 12, 1)),
    ("ASX_Investment_Products_Sep_26.xlsx", date(2026, 9, 1)),
    ("asx-investment-products-2026-07.xlsx", date(2026, 7, 1)),
    ("ASX Investment Products - March 2026", date(2026, 3, 1)),
    ("investment-products.xlsx", None),
])
def test_month_from_name(name, expected):
    assert month_from_name(name) == expected


def test_report_links_newest_first_and_xlsx_only():
    html = """
      <a href="/content/dam/asx/issuers/asx-investment-products-reports/2026/excel/asx-investment-products-jul-2026.xlsx">Jul</a>
      <a href='https://www.asx.com.au/content/dam/asx/x/asx-investment-products-aug-2026.xlsx?v=2'>Aug</a>
      <a href="/content/dam/asx/x/asx-investment-products-aug-2026.pdf">Aug PDF</a>
      <a href="/content/dam/asx/x/glossary.xlsx">no month</a>"""
    links = report_links(html)
    assert [m for m, _ in links] == [date(2026, 8, 1), date(2026, 7, 1)]
    assert links[0][1] == "https://www.asx.com.au/content/dam/asx/x/asx-investment-products-aug-2026.xlsx"
    assert links[1][1].startswith("https://www.asx.com.au/content/dam/asx/issuers/")


def test_guessed_urls_follow_the_pdf_pattern():
    urls = asx_report.guessed_urls(date(2026, 8, 1))
    assert f"{asx_report.REPORT_BASE}/2026/excel/asx-investment-products-aug-2026.xlsx" in urls


@pytest.mark.parametrize("label,field", [
    ("ASX Code", "code"), ("ASX code", "code"), ("Ticker", "code"), ("Fund details ASX Code", "code"),
    ("Fund Name", "fund_name"), ("ETP name", "fund_name"),
    ("Issuer", "issuer"), ("Product issuer", "issuer"), ("Fund manager", "issuer"),
    ("Type", "product_type"), ("Product type", "product_type"),
    ("Exposure", "category"), ("Asset class", "category"), ("Sub-category", "sub_category"),
    ("Benchmark", "benchmark"), ("Index", "benchmark"),
    ("Management Fee", "mer_percent"), ("MER (%)", "mer_percent"), ("ICR", "mer_percent"),
    ("FUM ($m)", "fum_aud"), ("Market cap ($m)", "fum_aud"), ("Funds under management", "fum_aud"),
    ("Net Flows ($m)", "net_flows_aud"), ("Avg Bid/Ask Spread", "avg_spread_percent"),
    ("Value traded ($m)", "value_traded_aud"), ("Distribution yield (%)", "distribution_yield"),
    ("Distribution frequency", "distribution_frequency"), ("Listing date", "listing_date"),
    ("1 Month", "return_1m"), ("3 Mth Return (%)", "return_3m"), ("Performance 6 months", "return_6m"),
    ("1 Year", "return_1y"), ("12 month total return", "return_1y"), ("3 Yr Return (%)", "return_3y"),
    ("Performance (%) 5 Year", "return_5y"), ("10 Years p.a.", "return_10y"),
    ("Since Inception (%)", "return_since_inception"),
    ("Net flows 1 Year", "net_flows_aud"), ("Notes", None), ("", None),
])
def test_match_field(label, field):
    assert match_field(label) == field


def test_group_heading_decides_bare_periods_but_not_named_columns():
    assert asx_report.column_field("Flows ($m) 1 Year", "1 Year") == "net_flows_aud"
    assert asx_report.column_field("Performance (%) 1 Year", "1 Year") == "return_1y"
    assert asx_report.column_field("Size and flows FUM ($m)", "FUM ($m)") == "fum_aud"


def test_grouped_layout(tmp_path):
    report = read_report(build_report(tmp_path))
    assert report.month == date(2026, 8, 1)
    assert sorted(report.rows) == ["GOLD", "HACK", "IOZ", "NDQ", "VAS"]  # no LIC, no Total row
    assert report.skipped_sheets == []
    assert list(report.lics) == ["ARG"]  # the LIC sheet is read separately (§27)
    vas = report.rows["VAS"]
    assert vas["fund_name"] == "Vanguard Australian Shares Index ETF"
    assert vas["issuer"] == "Vanguard" and vas["category"] == "Australian Equities"
    assert vas["mer_percent"] == Decimal("0.07")          # an Excel percent: 0.0007 shown as 0.07%
    assert vas["avg_spread_percent"] == Decimal("0.02")
    assert vas["fum_aud"] == Decimal("18500500000")       # $m
    assert vas["net_flows_aud"] == Decimal("210200000")
    assert vas["return_1y"] == Decimal("12.5") and vas["return_10y"] == Decimal("8.9")
    assert report.rows["IOZ"].get("return_10y") is None
    assert vas["raw"]["Performance (%) 1 Year"] == 12.5
    assert report.rows["HACK"]["product_type"] == "Active ETF"


def test_flat_layout(tmp_path):
    report = read_report(build_report(tmp_path, "asx-investment-products-2026-07.xlsx", layout="flat"))
    assert report.month == date(2026, 7, 1)
    vas = report.rows["VAS"]
    assert vas["mer_percent"] == Decimal("0.07")           # already a whole-number percent
    assert vas["fum_aud"] == Decimal("18500500000")       # dollars, left as they are
    assert vas["return_since_inception"] == Decimal("7.5")
    assert vas["listing_date"] == date(2009, 5, 4)
    assert vas["distribution_frequency"] == "Quarterly"


def test_fractions_without_a_percent_format_are_scaled(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "ETPs"
    ws.append(["ASX Code", "Name", "MER", "1 Yr Return", "FUM"])
    for i, code in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
        ws.append([code, f"Fund {code}", 0.0005 + i / 10000, 0.10 + i / 100, 50 + i])  # fractions; FUM in $m
    path = tmp_path / "asx-investment-products-may-2026.xlsx"
    wb.save(path)
    report = read_report(path)
    assert report.rows["AAA"]["mer_percent"] == Decimal("0.05")
    assert report.rows["AAA"]["return_1y"] == Decimal("10.0")
    assert report.rows["AAA"]["fum_aud"] == Decimal("50000000")
    notes = " ".join(report.sheets[0].notes)
    assert "mer_percent" in notes and "returns" in notes and "millions" in notes


def test_month_found_in_a_title_cell(tmp_path):
    path = build_report(tmp_path, "report.xlsx")
    assert read_report(path).month == date(2026, 8, 1)  # "ASX Investment Products - August 2026"


def test_not_a_report(tmp_path):
    wb = Workbook()
    wb.active.append(["Something", "else", "entirely"])
    path = tmp_path / "other.xlsx"
    wb.save(path)
    with pytest.raises(ReportError, match="No ETP list"):
        read_report(path)
    junk = tmp_path / "junk.xlsx"
    junk.write_text("not a spreadsheet")
    with pytest.raises(ReportError, match="can't be opened"):
        read_report(junk)


def test_describe_shows_the_mapping(tmp_path):
    text = asx_report.describe(read_report(build_report(tmp_path)))
    assert "Report month: August 2026" in text
    assert "Fund details Management Fee" in text and "-> mer_percent" in text
    assert "Sheet 'LIC Spotlight'" in text and "LICs and LITs" in text


def test_download_prefers_the_page_links_and_stops_at_what_is_loaded(tmp_path):
    xlsx = build_report(tmp_path / "..", "src.xlsx").read_bytes()
    page = b'<a href="/x/asx-investment-products-aug-2026.xlsx">x</a><a href="/x/asx-investment-products-jul-2026.xlsx">y</a>'
    asked = []

    def fetch(url):
        asked.append(url)
        return page if url == asx_report.REPORT_PAGE else xlsx

    found = asx_report.download_newer(date(2026, 7, 1), date(2026, 9, 10), fetch, tmp_path / "reports")
    assert found[0] == date(2026, 8, 1)
    assert found[1].name == "asx-investment-products-2026-08.xlsx" and found[1].exists()
    assert asked == [asx_report.REPORT_PAGE, "https://www.asx.com.au/x/asx-investment-products-aug-2026.xlsx"]

    asked.clear()
    assert asx_report.download_newer(date(2026, 8, 1), date(2026, 9, 10), fetch, tmp_path / "reports") is None
    assert asked == [asx_report.REPORT_PAGE]  # nothing newer on the page: nothing downloaded


def test_download_falls_back_to_expected_addresses(tmp_path):
    xlsx = build_report(tmp_path, "src.xlsx").read_bytes()
    wanted = asx_report.guessed_urls(date(2026, 8, 1))[0]
    found = asx_report.download_newer(None, date(2026, 9, 10), lambda url: xlsx if url == wanted else None,
                                      tmp_path / "reports")
    assert found[0] == date(2026, 8, 1)
    # A page that answers with something other than a spreadsheet isn't saved.
    assert asx_report.download_newer(None, date(2026, 9, 10), lambda url: b"<html>", tmp_path / "none") is None


def test_local_file_is_picked_up(tmp_path):
    build_report(tmp_path, "asx-investment-products-aug-2026.xlsx")
    build_report(tmp_path, "asx-investment-products-jul-2026.xlsx")
    assert asx_report.local_newer(date(2026, 7, 1), tmp_path)[0] == date(2026, 8, 1)
    assert asx_report.local_newer(date(2026, 8, 1), tmp_path) is None
    assert asx_report.local_newer(None, tmp_path / "missing") is None


def test_expected_month():
    assert asx_report.expected_month(date(2026, 10, 6)) == date(2026, 9, 1)
    assert asx_report.expected_month(date(2026, 1, 20)) == date(2025, 12, 1)


def test_the_real_2026_layout(tmp_path):
    """Built to match the July 2026 report: categories from section rows,
    fractions scaled, index rows, other sheets and footnotes left out."""
    report = read_report(build_asx_2026(tmp_path))
    assert report.month == date(2026, 7, 1)
    assert sorted(report.rows) == ["G200", "GOLD", "HACK", "NDQ", "VAS"]  # not XJO, AFI or the notes
    assert set(report.skipped_sheets) == {"Spotlight ETPs", "Spotlight A-REITS  List", "Spotlight Infra  List"}
    vas = report.rows["VAS"]
    assert vas["category"] == "Equity - Australia" and vas["product_type"] == "ETF"
    assert vas["mer_percent"] == Decimal("0.07")                 # already a percent
    assert vas["fum_aud"] == Decimal("26170070000.00")
    assert vas["net_flows_aud"] == Decimal("412500000.0")
    assert vas["value_traded_aud"] == Decimal("900000000.5")
    assert vas["avg_spread_percent"] == Decimal("0.0223")        # a fraction, scaled
    assert vas["distribution_yield"] == Decimal("2.93")
    assert vas["return_1y"] == Decimal("6.71") and vas["return_5y"] == Decimal("9.06")
    assert report.rows["HACK"]["return_1y"] == Decimal("115.12")  # one 115% year doesn't stop the scaling
    assert report.rows["GOLD"]["category"] == "Commodity" and report.rows["GOLD"]["product_type"] == "Structured product"
    assert report.rows["HACK"]["product_type"] == "Active ETF"
    assert report.rows["G200"]["raw"][asx_report.FUND_OF_FUNDS] is True
    assert asx_report.FUND_OF_FUNDS not in vas["raw"]
    assert report.rows["G200"].get("return_3y") is None          # "n/a"
    notes = " ".join(report.sheets[0].notes)
    assert "category: taken from the section headings" in notes and "returns: written as fractions" in notes


def test_the_real_2026_lic_list(tmp_path):
    """The LIC sheet: Shares are LICs and Units LITs, NTA and its premium
    or discount, the performance fee flag, market cap written with commas,
    index rows left out."""
    lics = read_report(build_asx_2026(tmp_path)).lics
    assert sorted(lics) == ["AFI", "ARG", "BKI", "MXT", "WAM"]
    afi = lics["AFI"]
    assert afi["product_type"] == "LIC" and lics["MXT"]["product_type"] == "LIT"
    assert afi["category"] == "Equity - Australia" and lics["MXT"]["category"] == "Fixed Income - Australian Dollar"
    assert afi["nta_pre_tax"] == Decimal("7.93") and afi["nta_date"] == date(2026, 6, 30)
    assert afi["nta_premium_percent"] == Decimal("-11.097")       # a fraction, scaled
    assert lics["WAM"]["nta_premium_percent"] == Decimal("5.25")
    assert afi["performance_fee"] == "No" and lics["WAM"]["performance_fee"] == "Yes"
    assert afi["mer_percent"] == Decimal("0.16")
    assert afi["fum_aud"] == Decimal("8421430000.00")               # "8,421.43" in $m
    assert afi["distribution_yield"] == Decimal("3.759") and afi["return_1y"] == Decimal("-4.817")


@pytest.mark.parametrize("label,field", [
    ("Prem/Disc % NTA (pre-tax) at NTA Date", "nta_premium_percent"), ("NTA Date", "nta_date"),
    ("NTA Price", "nta_pre_tax"), ("Pre-Tax NTA ($)", "nta_pre_tax"), ("Post Tax NTA ($)", None),
    ("Outperf Fee", "performance_fee"), ("Mkt Cap ($m)#", "fum_aud"),
])
def test_lic_headings(label, field):
    assert match_field(label) == field


def test_sheet_kinds():
    names = ["Spotlight ETPs", "Spotlight ETPs Issuers", "Spotlight ETP List", "Spotlight LIC List",
             "Spotlight A-REITS  List", "Spotlight Infra  List"]
    assert [asx_report.sheet_kind(n, names) for n in names] == ["ETF", None, "ETF", "LIC", None, None]


def test_guessed_urls_try_the_full_month_name_first():
    urls = asx_report.guessed_urls(date(2026, 7, 1))
    assert urls[0] == f"{asx_report.REPORT_BASE}/2026/excel/asx-investment-products-july-2026-abs.xlsx"
