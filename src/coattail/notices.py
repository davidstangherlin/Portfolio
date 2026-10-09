"""ASX director trades and substantial holder notices (docs/kb/features/coattail.md).

Each night, after the market closes:

1. Read ASX's lists of the day's announcements and the previous business
   day's (every listed company, one page each), keeping the titles Sift
   follows: director interest notices (Appendix 3Y) and substantial holder
   notices ("Becoming", "Change in", "Ceasing"). See notice_reader.classify().
2. Save each new notice (`asx_notices`), linked to the company when Sift
   follows it.
3. Download each unread notice's PDF and read the details
   (notice_reader.py) into `director_trades` or `substantial_holdings`.
   A PDF that fails to download is tried again on the next two nights.

    python -m src.coattail.notices                 # the nightly run
    python -m src.coattail.notices --dry-run       # fetch and read a few, print, save nothing
    python -m src.coattail.notices --codes BHP PLS # six months of these companies' notices
    python -m src.coattail.notices --mine          # six months for everything you hold or watch
    python -m src.coattail.notices --html page.html  # a list page saved from the browser
    python -m src.coattail.notices --reread        # read every notice again with the current reader

ASX turns away plain scripted requests, so pages are fetched with a
browser's fingerprint (curl_cffi, installed with yfinance), as the ETF
report download does, with a pause between requests."""

from __future__ import annotations

import argparse
import html as htmllib
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from src.coattail import notice_reader as reader
from src.coattail.views import manager_of

logger = logging.getLogger(__name__)

ASX = "https://www.asx.com.au"
LIST_PAGES = (f"{ASX}/asx/v2/statistics/todayAnns.do", f"{ASX}/asx/v2/statistics/prevBusDayAnns.do")
COMPANY_PAGE = ASX + "/asx/v2/statistics/announcements.do?by=asxCode&asxCode={code}&timeframe=D&period=M6"
SYDNEY = ZoneInfo("Australia/Sydney")
PAUSE = 1.0           # seconds between requests to ASX
MAX_ATTEMPTS = 3      # nights a PDF that won't download is tried
READ_LIMIT = 600      # PDFs read in one run (a normal day has 50 to 150)


# ---------- fetching ----------
def get(url: str) -> tuple[int, bytes]:
    """(status, body); status 0 when the request itself failed."""
    time.sleep(PAUSE)
    try:
        from curl_cffi import requests as http
        r = http.get(url, impersonate="chrome", timeout=60)
        return r.status_code, r.content
    except ImportError:
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
                return r.status, r.read()
        except HTTPError as e:
            return e.code, b""
        except OSError:
            return 0, b""
    except Exception:  # noqa: BLE001 - a network failure is reported, not fatal
        logger.debug("Request failed: %s", url, exc_info=True)
        return 0, b""


def get_pdf(url: str, fetch=None) -> bytes | None:
    """The notice's PDF. ASX's link may answer with a page (its terms of use)
    that names the PDF's real address; follow it once."""
    fetch = fetch or get
    status, body = fetch(url)
    if status == 200 and body[:5] == b"%PDF-":
        return body
    if status == 200 and body:
        page = body.decode("utf-8", "replace")
        m = (re.search(r'name="pdfURL"\s+value="([^"]+)"', page) or re.search(r'value="([^"]+\.pdf)"', page)
             or re.search(r'href="([^"]+\.pdf)"', page))
        if m:
            link = htmllib.unescape(m.group(1))
            status, body = fetch(link if link.startswith("http") else ASX + link)
            if status == 200 and body[:5] == b"%PDF-":
                return body
    return None


# ---------- the announcement lists ----------
@dataclass
class Listing:
    notice_id: str
    asx_code: str
    released_at: datetime
    headline: str
    kind: str
    price_sensitive: bool
    pages: int | None
    pdf_url: str


def _strip(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_list(page: str, default_code: str | None = None, page_date: date | None = None) -> list[Listing]:
    """The followed notices on an ASX announcements list (the day's, the
    previous business day's, or one company's). Rows without a date take
    the first date on the page, then `page_date`."""
    page_wide = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", page)
    fallback = reader.parse_date(page_wide.group(1)) if page_wide else page_date
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        link = re.search(r'href="([^"]*displayAnnouncement\.do\?[^"]*idsId=(\d+)[^"]*)"', row, re.I)
        if not link:
            continue
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        texts = [_strip(c) for c in cells]
        code = default_code or next((t for t in texts if re.fullmatch(r"[A-Z0-9]{3,6}", t) and t != "PDF"), None)
        cell = next((c for c in cells if "idsId" in c), row)
        headline = _strip(cell)
        headline = re.sub(r"\b\d+\s+pages?\b|\b\d+(\.\d+)?\s*[KM]B\b|\bPDF\b", " ", headline, flags=re.I)
        headline = re.sub(r"\s+", " ", headline).strip()
        kind = reader.classify(headline)
        if not code or not kind:
            continue
        flat = " ".join(texts)
        day = reader.parse_date(flat) or fallback or datetime.now(SYDNEY).date()
        clock = re.search(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?m\b", flat, re.I)
        at = dtime(0, 0)
        if clock:
            hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "p" else 0)
            at = dtime(hour, int(clock.group(2)))
        pages = re.search(r"\b(\d+)\s+pages?\b", _strip(row), re.I)
        out.append(Listing(
            notice_id=link.group(2), asx_code=code, released_at=datetime.combine(day, at, SYDNEY), headline=headline[:500],
            kind=kind, price_sensitive=bool(re.search(r'alt="asterix"|title="price sensitive"|class="[^"]*pricesens[^"]*"[^>]*>\s*<img', row, re.I)),
            pages=int(pages.group(1)) if pages else None,
            pdf_url=(ASX + htmllib.unescape(link.group(1))) if link.group(1).startswith("/") else htmllib.unescape(link.group(1))))
    return out


def fetch_lists(urls=LIST_PAGES, fetch=None, code: str | None = None) -> tuple[list[Listing], list[str]]:
    """(the followed notices, problems) from each list page; `code` for one
    company's page, which has no code column."""
    fetch = fetch or get
    found: dict[str, Listing] = {}
    problems = []
    for url in urls:
        status, body = fetch(url)
        if status != 200 or not body:
            problems.append(f"{url}: {status or 'no answer'}")
            continue
        rows = parse_list(body.decode("utf-8", "replace"), default_code=code, page_date=datetime.now(SYDNEY).date())
        if not rows and b"idsId" not in body:
            problems.append(f"{url}: no announcements found on the page")
        for r in rows:
            found.setdefault(r.notice_id, r)
    return list(found.values()), problems


# ---------- saving and reading ----------
def save(session, listings: list[Listing]) -> int:
    """Save new notices; returns how many were new."""
    new = 0
    for n in listings:
        result = session.execute(text("""
            INSERT INTO asx_notices (notice_id, asx_code, company_id, released_at, headline, kind, price_sensitive, pages, pdf_url)
            VALUES (:id, :code, (SELECT company_id FROM companies WHERE asx_code = :code), :at, :headline, :kind, :ps, :pages, :url)
            ON CONFLICT (notice_id) DO NOTHING"""),
            {"id": n.notice_id, "code": n.asx_code, "at": n.released_at, "headline": n.headline, "kind": n.kind,
             "ps": n.price_sensitive, "pages": n.pages, "url": n.pdf_url})
        new += result.rowcount or 0
    session.execute(text("""
        UPDATE asx_notices n SET company_id = c.company_id FROM companies c
        WHERE n.company_id IS NULL AND c.asx_code = n.asx_code"""))  # companies added to Sift since
    return new


@dataclass
class Reading:
    status: str
    entity: str | None = None
    note: str | None = None
    trades: list | None = None
    holding: reader.SubstantialHolding | None = None


def read_pdf(kind: str, content: bytes | None) -> Reading:
    if content is None:
        return Reading("failed", note="the PDF didn't download")
    try:
        body = reader.pdf_text(content)
    except Exception as exc:  # noqa: BLE001 - a damaged PDF is noted, not fatal
        return Reading("unreadable", note=f"the PDF couldn't be opened ({type(exc).__name__})")
    if len(body.strip()) < 40:
        return Reading("unreadable", note="the PDF has no text (probably a scanned image)")
    if kind == "DIRECTOR":
        entity, trades = reader.read_3y(body)
        if not trades:
            return Reading("partial", entity=entity, note="no director's details found", trades=[])
        return Reading("read" if all(t.complete for t in trades) else "partial", entity=entity, trades=trades,
                       note=None if all(t.complete for t in trades) else "some details not found")
    holding = reader.read_substantial(body, kind)
    return Reading("read" if holding.complete else "partial", entity=holding.entity, holding=holding,
                   note="; ".join(holding.notes) or (None if holding.complete else "some details not found"))


def store_reading(session, notice_id: str, kind: str, headline: str, r: Reading) -> None:
    session.execute(text("DELETE FROM director_trades WHERE notice_id = :id"), {"id": notice_id})
    session.execute(text("DELETE FROM substantial_holdings WHERE notice_id = :id"), {"id": notice_id})
    for i, t in enumerate(r.trades or [], start=1):
        session.execute(text("""
            INSERT INTO director_trades (notice_id, line_no, director, interest, change_date, security_class, acquired, disposed,
                                         consideration, price, held_after, nature, nature_kind, direction)
            VALUES (:id, :n, :director, :interest, :change_date, :cls, :acquired, :disposed, :consideration, :price,
                    :held_after, :nature, :nature_kind, :direction)"""),
            {"id": notice_id, "n": i, "director": t.director, "interest": t.interest, "change_date": t.change_date,
             "cls": t.security_class, "acquired": t.acquired, "disposed": t.disposed, "consideration": t.consideration,
             "price": t.price, "held_after": t.held_after, "nature": t.nature, "nature_kind": t.nature_kind, "direction": t.direction})
    if kind != "DIRECTOR" and r.status in ("read", "partial", "unreadable"):
        h = r.holding or reader.SubstantialHolding()
        holder = h.holder or reader.holder_from_headline(headline)
        session.execute(text("""
            INSERT INTO substantial_holdings (notice_id, holder, manager, event_date, previous_pct, present_pct, votes)
            VALUES (:id, :holder, :manager, :date, :prev, :now, :votes)"""),
            {"id": notice_id, "holder": holder, "manager": manager_of(reader.holder_group(holder)) if holder else None, "date": h.event_date,
             "prev": h.previous_pct, "now": h.present_pct if r.holding else None, "votes": h.votes})
    session.execute(text("""
        UPDATE asx_notices SET read_status = :s, read_note = :note, entity_name = coalesce(:entity, entity_name),
               reader_version = :v, read_at = CURRENT_TIMESTAMP, read_attempts = read_attempts + 1
        WHERE notice_id = :id"""), {"s": r.status, "note": r.note, "entity": r.entity, "v": reader.READER_VERSION, "id": notice_id})


def read_unread(session, fetch=None, limit: int = READ_LIMIT, reread: bool = False) -> dict[str, int]:
    """Download and read notices not yet read (and failed ones, up to
    MAX_ATTEMPTS nights); with `reread`, every notice read by an older reader."""
    where = ("reader_version IS NULL OR reader_version < :v OR read_status IN ('pending', 'failed')" if reread
             else "read_status = 'pending' OR (read_status = 'failed' AND read_attempts < :max)")
    rows = session.execute(text(f"""
        SELECT notice_id, kind, headline, pdf_url FROM asx_notices WHERE {where}
        ORDER BY released_at DESC LIMIT :limit"""), {"v": reader.READER_VERSION, "max": MAX_ATTEMPTS, "limit": limit}).all()
    counts: dict[str, int] = {}
    for notice_id, kind, headline, url in rows:
        r = read_pdf(kind, get_pdf(url, fetch))
        store_reading(session, notice_id, kind, headline, r)
        session.commit()  # each notice is saved as it's read, so a stopped run keeps its work
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def my_codes(session) -> list[str]:
    """The ASX codes the current user holds or watches."""
    from src.portfolio.holdings import open_parcels
    from src.watchlist.lists import watched_codes
    return sorted({p.asx_code for p in open_parcels(session)} | set(watched_codes(session)))


# ---------- the command ----------
def describe(n: Listing, r: Reading | None) -> str:
    line = f"{n.released_at:%d/%m %H:%M} {n.asx_code:<6} {reader.KINDS[n.kind]:<34} {n.headline[:60]}"
    if r is None:
        return line
    if r.trades:
        t = r.trades[0]
        line += (f"\n      {r.status}: {t.director} {t.direction.lower()} acquired {t.acquired} disposed {t.disposed}"
                 f" ${t.consideration} at ${t.price} ({t.nature_kind.lower()}: {t.nature})")
    elif r.holding:
        h = r.holding
        line += f"\n      {r.status}: {h.holder} on {h.event_date}: {h.previous_pct}% -> {h.present_pct}%"
    else:
        line += f"\n      {r.status}: {r.note}"
    return line


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Load ASX director trades and substantial holder notices.")
    p.add_argument("--dry-run", action="store_true", help="fetch and read a few, print them, save nothing")
    p.add_argument("--codes", nargs="+", metavar="CODE", help="six months of these companies' notices instead of the day's lists")
    p.add_argument("--mine", action="store_true", help="six months for every company you hold or watch")
    p.add_argument("--html", type=Path, help="read a list page saved from the browser instead of fetching")
    p.add_argument("--reread", action="store_true", help="read every notice again with the current reader")
    p.add_argument("--limit", type=int, default=None, help=f"PDFs to read (default {READ_LIMIT}; 5 in a dry run)")
    args = p.parse_args(argv)
    limit = args.limit or (5 if args.dry_run else READ_LIMIT)

    from src.config import get_session
    with get_session() as session:
        problems: list[str] = []
        if args.html:
            listings = parse_list(args.html.read_text(encoding="utf-8", errors="replace"))
        elif args.codes or args.mine:
            codes = [c.upper() for c in args.codes] if args.codes else my_codes(session)
            listings, problems = [], []
            for code in codes:
                rows, issues = fetch_lists([COMPANY_PAGE.format(code=code)], code=code)
                listings += rows
                problems += issues
        elif not args.reread:
            listings, problems = fetch_lists()
        else:
            listings = []
        for issue in problems:
            logger.warning("ASX notices: %s", issue)
        by_kind = {k: sum(1 for n in listings if n.kind == k) for k in reader.KINDS}
        logger.info("ASX notices: %d followed (%d director, %d substantial holder)", len(listings), by_kind["DIRECTOR"],
                    len(listings) - by_kind["DIRECTOR"])
        if args.dry_run:
            for i, n in enumerate(sorted(listings, key=lambda x: x.released_at, reverse=True)):
                print(describe(n, read_pdf(n.kind, get_pdf(n.pdf_url)) if i < limit else None))
            return 0 if listings or not problems else 1
        new = save(session, listings)
        session.commit()
        counts = read_unread(session, limit=limit, reread=args.reread)
        logger.info("ASX notices: %d new; read %s", new, ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "nothing")
        return 1 if problems and not listings and not args.reread else 0


if __name__ == "__main__":
    sys.exit(main())
