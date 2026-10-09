"""Reading ASX director and substantial holder notices (docs/kb/features/coattail.md):
which titles are followed, the details read from each form, and the
announcement list pages. The PDFs in tests/fixtures/notices are laid out
like the real forms (label beside value), so their text comes out the way
ASX's PDFs' text does."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.coattail import notice_reader as r
from src.coattail import notices

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "notices"


@pytest.mark.parametrize("headline, kind", [
    ("Change of Director's Interest Notice", "DIRECTOR"),
    ("Change of Directors' Interest Notice - J Citizen", "DIRECTOR"),
    ("Appendix 3Y - Jane Citizen", "DIRECTOR"),
    ("Becoming a substantial holder", "SUBSTANTIAL_NEW"),
    ("Becoming a substantial holder from Vanguard", "SUBSTANTIAL_NEW"),
    ("Change in substantial holding", "SUBSTANTIAL_CHANGE"),
    ("Change in substantial holding for GMN", "SUBSTANTIAL_CHANGE"),
    ("Ceasing to be a substantial holder", "SUBSTANTIAL_CEASE"),
    ("Change in Chief Executive Officer", None),     # "Change in", but not a holding
    ("Becoming a member of the S&P/ASX 200", None),
    ("Change of Directors", None),                   # board changes, not trades
    ("Initial Director's Interest Notice", None),    # Appendix 3X: not followed
    ("Quarterly Activities Report", None),
])
def test_titles_followed(headline, kind):
    assert r.classify(headline) == kind


def test_holder_named_in_a_title():
    assert r.holder_from_headline("Change in substantial holding from Vanguard") == "Vanguard"
    assert r.holder_from_headline("Becoming a substantial holder for Perpetual Limited") == "Perpetual Limited"
    assert r.holder_from_headline("Becoming a substantial holder") is None


def test_appendix_3y_pdf():
    entity, trades = r.read_3y(r.pdf_text((FIXTURES / "3y.pdf").read_bytes()))
    assert entity == "Good Mining Limited" and len(trades) == 1
    t = trades[0]
    assert (t.director, t.interest, t.change_date) == ("Jane Citizen", "indirect", date(2026, 10, 2))
    assert (t.acquired, t.disposed, t.consideration, t.price) == (Decimal(50000), 0, Decimal(212500), Decimal("4.25"))
    assert (t.nature, t.nature_kind, t.direction) == ("On-market trade", "ON_MARKET", "BUY")  # not the form's example text
    assert t.held_after.startswith("Direct: 120,000") and t.complete


def test_appendix_3y_text_variants():
    two = """Appendix 3Y Change of Director's Interest Notice
Name of entity Big Bank Limited ABN 11 222 333 444
Name of Director Sam Seller Date of last notice 1/02/2026
Direct or indirect interest Direct
Date of change 05/10/2026 No. of securities held prior to change 80,000
Class Ordinary Number acquired - Number disposed 20,000
Value/Consideration $45.10 per share
No. of securities held after change 60,000 Nature of change Off-market transfer to spouse
Part 2 - Change of director's interests in contracts
Name of Director Pat Holder Date of last notice 1/02/2026
Direct or indirect interest Direct and indirect
Date of change 6 Oct 2026 No. of securities held prior to change 1,000 Class Ordinary
Number acquired 312 Number disposed Nil Value/Consideration $1.4m
No. of securities held after change 1,312 Nature of change Participation in dividend reinvestment plan
Part 2 - Change of director's interests in contracts"""
    entity, trades = r.read_3y(two)
    assert entity == "Big Bank Limited" and [t.director for t in trades] == ["Sam Seller", "Pat Holder"]
    sell, drp = trades
    assert (sell.direction, sell.disposed, sell.price, sell.consideration) == ("SELL", 20000, Decimal("45.10"), Decimal("902000.00"))
    assert sell.nature_kind == "OFF_MARKET" and sell.change_date == date(2026, 10, 5)
    assert (drp.direction, drp.acquired, drp.consideration, drp.interest) == ("BUY", 312, Decimal(1_400_000), "both")
    assert drp.nature_kind == "DRP" and drp.change_date == date(2026, 10, 6)


@pytest.mark.parametrize("nature, kind", [
    ("On-market trade", "ON_MARKET"), ("On market purchase", "ON_MARKET"), ("Off-market transfer", "OFF_MARKET"),
    ("Exercise of options", "EXERCISE"), ("Vesting of performance rights", "EXERCISE"),
    ("Issue of performance rights under LTI plan", "ISSUE"), ("Participation in SPP", "ISSUE"),
    ("Dividend reinvestment plan", "DRP"), ("Transfer between entities", "OTHER"), (None, "OTHER"),
])
def test_nature_of_change(nature, kind):
    assert r.nature_kind(nature) == kind


def test_form_604_pdf():
    h = r.read_substantial(r.pdf_text((FIXTURES / "604.pdf").read_bytes()), "SUBSTANTIAL_CHANGE")
    assert (h.holder, h.entity, h.event_date) == ("Perpetual Limited and its related bodies corporate", "Good Mining Limited", date(2026, 10, 3))
    assert (h.previous_pct, h.present_pct, h.votes) == (Decimal("6.12"), Decimal("7.15"), Decimal(7154210)) and h.complete


def test_forms_603_and_605_text():
    new = """Form 603 Corporations Act 2001 Section 671B Notice of initial substantial holder
To Company Name/Scheme Good Mining Limited ACN/ARSN 345 678 901
1. Details of substantial holder (1) Name The Vanguard Group, Inc. ACN/ARSN (if applicable) N/A
The holder became a substantial holder on 02/10/2026
2. Details of voting power
The total number of votes attached to all the voting shares ... became a substantial holder are as follows:
Class of securities (4) Number of securities Person's votes (5) Voting power (6)
Fully Paid Ordinary 5,012,345 5,012,345 5.01%
3. Details of relevant interests"""
    h = r.read_substantial(new, "SUBSTANTIAL_NEW")
    assert (h.holder, h.event_date, h.present_pct, h.votes) == ("The Vanguard Group, Inc.", date(2026, 10, 2), Decimal("5.01"), Decimal(5012345))
    gone = """Form 605 Notice of ceasing to be a substantial holder To Company Name/Scheme Good Mining Limited ACN/ARSN 345 678 901
1. Details of substantial holder(1) Name Regal Funds Management Pty Limited ACN/ARSN (if applicable) 107 576 821
The holder ceased to be a substantial holder on 7 October 2026"""
    h = r.read_substantial(gone, "SUBSTANTIAL_CEASE")
    assert (h.holder, h.event_date, h.present_pct) == ("Regal Funds Management Pty Limited", date(2026, 10, 7), 0) and h.complete


def test_numbers_and_dates():
    assert r.first_number("Nil") == 0 and r.first_number("1,250,000 ordinary shares") == 1250000 and r.first_number("") is None
    assert r.money("$1,234.50") == (Decimal("1234.50"), False) and r.money("$4.50 per share") == (Decimal("4.50"), True)
    assert r.money("Average price of $2.10") == (Decimal("2.10"), True) and r.money("No cash consideration") == (None, False)
    assert r.parse_date("3/10/26") == date(2026, 10, 3) and r.parse_date("3rd October 2026") == date(2026, 10, 3)


TODAY_PAGE = """<html><h2>Company announcements released on 09/10/2026</h2><table>
<tr><th>ASX Code</th><th>Date</th><th>Price sens.</th><th>Headline</th></tr>
<tr><td>GMN</td><td>09/10/2026<br><span class="dates-time">4:12 pm</span></td><td class="pricesens">&nbsp;</td>
<td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03012345" target="_blank">Change of Director&#39;s Interest Notice
<span class="page">2 pages</span> <span class="filesize">98.1KB</span></a></td></tr>
<tr><td>GMN</td><td>09/10/2026<br>10:31 am</td><td class="pricesens"><img src="/images/asterix.gif" class="pricesens" alt="asterix" title="price sensitive"></td>
<td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03012346">Quarterly Activities Report 12 pages 1.2MB</a></td></tr>
<tr><td>BNK</td><td>09/10/2026<br>9:02 am</td><td class="pricesens">&nbsp;</td>
<td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03012347">Becoming a substantial holder from Perpetual 9 pages 300KB</a></td></tr>
</table></html>"""


def test_announcement_list_page():
    rows = notices.parse_list(TODAY_PAGE)
    assert [(x.notice_id, x.asx_code, x.kind) for x in rows] == [("03012345", "GMN", "DIRECTOR"), ("03012347", "BNK", "SUBSTANTIAL_NEW")]
    first = rows[0]
    assert first.headline == "Change of Director's Interest Notice" and first.pages == 2 and not first.price_sensitive
    assert first.released_at == datetime(2026, 10, 9, 16, 12, tzinfo=notices.SYDNEY)
    assert first.pdf_url == "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=03012345"
    assert rows[1].headline == "Becoming a substantial holder from Perpetual"


def test_one_companys_page_has_no_code_column():
    page = """<table><tr><td>05/10/2026<br>2:15 pm</td><td></td><td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=03011111">
Change in substantial holding</a></td></tr></table>"""
    rows = notices.parse_list(page, default_code="GMN")
    assert [(x.asx_code, x.kind, x.released_at.hour) for x in rows] == [("GMN", "SUBSTANTIAL_CHANGE", 14)]


def test_pdf_behind_the_terms_page_is_followed():
    pdf = (FIXTURES / "604.pdf").read_bytes()
    pages = {"https://x/notice": (200, b'<form><input type="hidden" name="pdfURL" value="/asxpdf/20261009/pdf/0abc.pdf"></form>'),
             "https://www.asx.com.au/asxpdf/20261009/pdf/0abc.pdf": (200, pdf)}
    assert notices.get_pdf("https://x/notice", lambda url: pages.get(url, (404, b""))) == pdf
    assert notices.get_pdf("https://x/missing", lambda url: (404, b"")) is None


def test_unreadable_and_failed_pdfs_are_noted():
    assert notices.read_pdf("DIRECTOR", None).status == "failed"
    assert notices.read_pdf("DIRECTOR", b"not a pdf").status == "unreadable"
    assert notices.read_pdf("SUBSTANTIAL_CHANGE", (FIXTURES / "604.pdf").read_bytes()).status == "read"
