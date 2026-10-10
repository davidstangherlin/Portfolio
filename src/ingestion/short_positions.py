"""ASIC's daily short position reports (docs/kb/features/volume-and-short-selling.md).

Short sellers (or their lenders) must report their short positions in ASX
products to ASIC, which publishes one file a day listing, for every product,
the shares reported short, the shares on issue and the percentage. Each file
covers one trading day and appears about four business days later, so
Sift's figure is always a few days behind.

    python -m src.ingestion.short_positions               # the days not yet loaded (nightly)
    python -m src.ingestion.short_positions --days 365    # a year of history
    python -m src.ingestion.short_positions --dry-run     # fetch the newest file, print, save nothing
    python -m src.ingestion.short_positions --file RR20261003-001-SSDailyAggShortPos.csv
    python -m src.ingestion.short_positions --folder          # every ASIC file saved in data/ASIC

Files saved from ASIC's website into data/ASIC (kept out of git) are also
loaded by the nightly run, if their day isn't loaded already.

The files are tab or comma separated and often UTF-16 encoded; the reader
finds its columns by name ("Product Code", "Reported Short Positions",
"Total Product in Issue", "% of Total Product in Issue Reported as Short
Positions") rather than position."""

from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)

URL = "https://download.asic.gov.au/short-selling/RR{day:%Y%m%d}-001-SSDailyAggShortPos.csv"
PAUSE = 1.0            # seconds between requests
NIGHTLY_DAYS = 14      # how far back the nightly run looks for files not yet loaded
STALE_DAYS = 8         # newest report older than this: warn (ASIC is normally about four business days behind)
KEEP_DAYS = 730        # two years of history
FOLDER = Path(__file__).resolve().parents[2] / "data" / "ASIC"   # files saved from ASIC's website


@dataclass
class ShortRow:
    asx_code: str
    short_positions: int
    shares_on_issue: int | None
    short_percent: Decimal


def get(url: str) -> tuple[int, bytes]:
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


def _decode(content: bytes) -> str:
    if content[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(content) > 3 and content[1:2] == b"\x00"):
        return content.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


def _num(raw: str) -> Decimal | None:
    s = re.sub(r"[^\d.\-]", "", (raw or "").replace(",", ""))
    if not s or s in ("-", "."):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse(content: bytes) -> list[ShortRow]:
    """Every product's short position in one ASIC file."""
    body = _decode(content)
    first = body.splitlines()[0] if body else ""
    delimiter = "\t" if "\t" in first else ","
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(body), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        return []
    head = [h.lower() for h in rows[0]]

    def col(*words, avoid=()):
        for i, h in enumerate(head):
            if all(w in h for w in words) and not any(a in h for a in avoid):
                return i
        return None
    code, short, issue, pct = col("code"), col("short", avoid=("%",)), col("issue", avoid=("%", "short")), col("%")
    if code is None or short is None:
        raise ValueError(f"unexpected columns: {', '.join(rows[0])}")
    out = []
    for r in rows[1:]:
        if len(r) <= max(i for i in (code, short, issue, pct) if i is not None):
            continue
        c = r[code].upper().strip()
        positions, on_issue = _num(r[short]), _num(r[issue]) if issue is not None else None
        percent = _num(r[pct]) if pct is not None else None
        if percent is None and positions is not None and on_issue:
            percent = positions / on_issue * 100
        if not re.fullmatch(r"[A-Z0-9]{2,6}", c) or positions is None or percent is None:
            continue
        out.append(ShortRow(c, int(positions), int(on_issue) if on_issue is not None else None,
                            percent.quantize(Decimal("0.0001"))))
    return out


def save(session, day: date, rows: list[ShortRow]) -> int:
    session.execute(text("DELETE FROM short_positions WHERE report_date = :d"), {"d": day})
    for r in rows:
        session.execute(text("""
            INSERT INTO short_positions (asx_code, report_date, company_id, short_positions, shares_on_issue, short_percent)
            VALUES (:code, :d, (SELECT company_id FROM companies WHERE asx_code = :code), :pos, :issue, :pct)"""),
            {"code": r.asx_code, "d": day, "pos": r.short_positions, "issue": r.shares_on_issue, "pct": r.short_percent})
    session.execute(text("DELETE FROM short_positions WHERE report_date < :cut"), {"cut": day - timedelta(days=KEEP_DAYS)})
    return len(rows)


def days_to_fetch(session, today: date, days: int) -> list[date]:
    """Weekdays in the last `days` not yet loaded, newest first (a missing
    file is a public holiday or not published yet: tried again next night)."""
    loaded = {d for (d,) in session.execute(text(
        "SELECT DISTINCT report_date FROM short_positions WHERE report_date >= :s"), {"s": today - timedelta(days=days)})}
    out = []
    for n in range(1, days + 1):
        d = today - timedelta(days=n)
        if d.weekday() < 5 and d not in loaded:
            out.append(d)
    return out


def date_of(name: str) -> date | None:
    m = re.search(r"RR(\d{8})", name)
    return datetime.strptime(m.group(1), "%Y%m%d").date() if m else None


def load_folder(session, folder: Path = FOLDER, only_new: bool = True) -> list[tuple[date, int]]:
    """Load the ASIC files saved in a folder (named as ASIC names them, which
    carries the date); with only_new, days already loaded are skipped."""
    if not folder.is_dir():
        return []
    done = {d for (d,) in session.execute(text("SELECT DISTINCT report_date FROM short_positions"))} if only_new else set()
    out = []
    for f in sorted(folder.glob("RR*.csv")):
        day = date_of(f.name)
        if day is None or day in done:
            continue
        out.append((day, save(session, day, parse(f.read_bytes()))))
        session.commit()
    return out


def run(session, today: date, days: int = NIGHTLY_DAYS, fetch=None, dry_run: bool = False,
        keep: Path | None = None) -> dict:
    """Load the days not yet loaded. Each file downloaded is also kept in
    `keep` (data/ASIC on the nightly run), so there's a copy on the PC.
    "refused" counts answers other than the file or "not found" (404): ASIC
    blocking the download, or the network, rather than a day not published."""
    if fetch is None:
        fetch, keep = get, (keep or FOLDER)
    loaded = missing = refused = 0
    statuses = set()
    if not dry_run and fetch is get:
        loaded += len(load_folder(session))  # anything saved by hand first, so it isn't fetched again
    for day in days_to_fetch(session, today, days):
        url = URL.format(day=day)
        status, content = fetch(url)
        if status != 200 or not content or content.lstrip()[:1] == b"<":
            if status in (200, 404):
                missing += 1
            else:
                refused += 1
                statuses.add(status)
            continue
        rows = parse(content)
        if dry_run:
            top = sorted(rows, key=lambda r: r.short_percent, reverse=True)[:10]
            print(f"{day}: {len(rows)} products; most shorted: " + ", ".join(f"{r.asx_code} {r.short_percent:.2f}%" for r in top))
            return {"loaded": 0, "missing": missing, "refused": refused}
        save(session, day, rows)
        session.commit()
        if keep is not None:
            keep.mkdir(parents=True, exist_ok=True)
            (keep / url.rsplit("/", 1)[-1]).write_bytes(content)
        loaded += 1
    if refused:
        logger.warning("ASIC refused %d request(s) (status %s): download the files from ASIC's short position reports "
                       "table into data\\ASIC and they load next run (runbook: rb-short-positions)",
                       refused, ", ".join(str(s) for s in sorted(statuses)))
    latest = session.execute(text("SELECT max(report_date) FROM short_positions")).scalar()
    if not dry_run and (latest is None or (today - latest).days > STALE_DAYS):
        logger.warning("Short positions are out of date: the newest ASIC report is %s", latest or "none")
    return {"loaded": loaded, "missing": missing, "refused": refused, "latest": latest}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Load ASIC's daily short position reports.")
    p.add_argument("--days", type=int, default=NIGHTLY_DAYS, help=f"how far back to look (default {NIGHTLY_DAYS})")
    p.add_argument("--dry-run", action="store_true", help="fetch the newest file, print the most shorted, save nothing")
    p.add_argument("--file", type=Path, help="load one ASIC file saved from the browser")
    p.add_argument("--folder", type=Path, nargs="?", const=FOLDER,
                   help="load every ASIC file in a folder (default data/ASIC), replacing days already loaded")
    args = p.parse_args(argv)
    from src.apply_schema import apply_schema
    from src.config import get_session
    apply_schema()  # idempotent: creates short_positions on a database Sift hasn't started on since the update
    with get_session() as session:
        if args.folder:
            for day, n in load_folder(session, args.folder, only_new=False):
                logger.info("Short positions: %d products for %s", n, day)
            return 0
        if args.file:
            day = date_of(args.file.name)
            if day is None:
                logger.error("The file name should keep ASIC's RRyyyymmdd date")
                return 1
            n = save(session, day, parse(args.file.read_bytes()))
            session.commit()
            logger.info("Short positions: %d products for %s", n, day)
            return 0
        counts = run(session, date.today(), args.days, dry_run=args.dry_run)
    logger.info("Short positions: %d days loaded, %d not published yet or holidays (weekends excluded), %d refused",
                counts["loaded"], counts["missing"], counts.get("refused", 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------- what the pages show ----------
CHANGE_DAYS = 30   # "rising" compares the latest report with the one about a month before


def company_short(session, asx_code: str, today: date) -> dict | None:
    """A company's short interest: the latest report, the change over about a
    month, and a year of history for the chart. None before any report."""
    rows = session.execute(text("""
        SELECT report_date, short_percent, short_positions, shares_on_issue FROM short_positions
        WHERE asx_code = :c AND report_date >= :s ORDER BY report_date"""),
        {"c": asx_code, "s": today - timedelta(days=366)}).all()
    if not rows:
        return None
    last = rows[-1]
    before = [r for r in rows if r.report_date <= last.report_date - timedelta(days=CHANGE_DAYS)]
    return {"report_date": last.report_date, "short_percent": last.short_percent, "short_positions": last.short_positions,
            "shares_on_issue": last.shares_on_issue,
            "change_points": (last.short_percent - before[-1].short_percent) if before else None,
            "history": [[r.report_date, r.short_percent] for r in rows]}


def most_shorted(session, held: set[str], watched: dict[str, list[str]], limit: int = 25) -> dict:
    """The most shorted ASX shares on the latest report, and those whose short
    interest rose most over about a month. Shares only (ETFs are shorted to hedge)."""
    latest = session.execute(text("SELECT max(report_date) FROM short_positions")).scalar()
    if latest is None:
        return {"as_of": None, "most": [], "rising": []}
    rows = [dict(r) for r in session.execute(text("""
        WITH now AS (SELECT * FROM short_positions WHERE report_date = :d),
             then_ AS (SELECT DISTINCT ON (asx_code) asx_code, short_percent FROM short_positions
                       WHERE report_date <= :before ORDER BY asx_code, report_date DESC)
        SELECT n.asx_code, coalesce(c.company_name, n.asx_code) AS company_name, c.company_id IS NOT NULL AS in_sift,
               c.sector, n.short_percent, n.short_positions, n.short_percent - t.short_percent AS change_points
        FROM now n LEFT JOIN companies c ON c.asx_code = n.asx_code
        LEFT JOIN then_ t ON t.asx_code = n.asx_code
        WHERE coalesce(c.security_type, 'SHARE') = 'SHARE'"""),
        {"d": latest, "before": latest - timedelta(days=CHANGE_DAYS)}).mappings()]
    from src.screening.short_caution import level
    for r in rows:
        r["caution"] = level(r["short_percent"], None, r["change_points"])
        r["held"] = r["asx_code"] in held
        r["watchlists"] = watched.get(r["asx_code"], [])
    most = sorted(rows, key=lambda r: r["short_percent"], reverse=True)[:limit]
    rising = sorted((r for r in rows if r["change_points"] is not None and r["change_points"] > 0),
                    key=lambda r: r["change_points"], reverse=True)[:limit]
    return {"as_of": latest, "most": most, "rising": rising}
