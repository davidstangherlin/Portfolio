"""Probe the data sources for Coattail's next stages (docs/AS_BUILT.md §31).

Read-only: fetches a few public web pages and files, prints what came back,
and saves the same report to logs/probe_coattail.txt. It touches nothing in
the database and needs nothing beyond Python's standard library.

    .venv\\Scripts\\python.exe scripts\\probe_coattail_sources.py

Checks:
  A. ASX announcements for a few companies, three ways, counting director
     interest notices (Appendix 3Y) and substantial holder notices
     (forms 603, 604, 605), and whether one notice's PDF downloads.
  B. Fund managers' holdings files for their ASX 200 ETFs (Vanguard VAS,
     iShares IOZ, SPDR STW, Betashares A200): every ASX company each holds.

Paste the report back (or the file) so the stages can be built on what
actually works from your connection. Some addresses are educated guesses;
a failure is a useful answer too.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CODES = ["BHP", "CBA", "WES", "PLS"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
DIRECTOR = re.compile(r"director'?s'? interest|appendix 3y", re.IGNORECASE)
SUBSTANTIAL = re.compile(r"substantial (holder|holding|shareholder)|form 60[345]", re.IGNORECASE)
PAUSE = 1.5  # seconds between requests: polite, and less likely to be blocked

LOG = Path(__file__).resolve().parent.parent / "logs" / "probe_coattail.txt"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def fetch(url: str, accept: str | None = None) -> tuple[int | str, str, bytes]:
    """(status, content type, body), never raising: a failure is reported, not fatal."""
    time.sleep(PAUSE)
    headers = dict(HEADERS, **({"Accept": accept} if accept else {}))
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as r:
            body = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower()
            if enc == "gzip":
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            return r.status, r.headers.get("Content-Type", ""), body
    except HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read()[:2000] if e.fp else b""
    except (URLError, TimeoutError, OSError) as e:
        return f"failed ({getattr(e, 'reason', e)})", "", b""


def snippet(body: bytes, n: int = 160) -> str:
    text = body[:4000].decode("utf-8", "replace")
    return re.sub(r"\s+", " ", text).strip()[:n]


def detail(body: bytes) -> None:
    """The start of a response, when there is one."""
    if body:
        say(f"      {snippet(body)}")


def tally(headlines: list[str]) -> str:
    d = sum(1 for x in headlines if DIRECTOR.search(x))
    s = sum(1 for x in headlines if SUBSTANTIAL.search(x))
    return f"{len(headlines)} announcements, {d} director interest, {s} substantial holder"


def show_matches(headlines: list[str], limit: int = 4) -> None:
    for x in [h for h in headlines if DIRECTOR.search(h) or SUBSTANTIAL.search(h)][:limit]:
        say(f"      - {x[:110]}")


# ---------- A. ASX announcements ----------
def markit(code: str) -> list[tuple[str, str]]:
    """ASX website's own data service (asx.api.markitdigital.com)."""
    url = f"https://asx.api.markitdigital.com/asx-research/1.0/companies/{code.lower()}/announcements"
    status, ctype, body = fetch(url, "application/json")
    say(f"  {code} markitdigital: {status} {ctype.split(';')[0]} {len(body)} bytes")
    if status != 200:
        detail(body)
        return []
    try:
        data = json.loads(body)
    except ValueError:
        say(f"      not JSON: {snippet(body)}")
        return []
    items = (data.get("data") or {}).get("items") or []
    if items:
        say(f"      fields: {', '.join(sorted(items[0].keys()))}")
    out = [(i.get("headline") or i.get("header") or "", i.get("documentKey") or i.get("url") or "") for i in items]
    say(f"      {tally([h for h, _ in out])}")
    show_matches([h for h, _ in out])
    return out


def legacy(code: str) -> None:
    """The older ASX announcements API."""
    url = f"https://www.asx.com.au/asx/1/company/{code}/announcements?count=20&market_sensitive=false"
    status, ctype, body = fetch(url, "application/json")
    say(f"  {code} asx/1 API: {status} {ctype.split(';')[0]} {len(body)} bytes")
    if status == 200:
        try:
            items = json.loads(body).get("data") or []
            heads = [i.get("header") or "" for i in items]
            say(f"      {tally(heads)}")
            show_matches(heads)
        except ValueError:
            say(f"      not JSON: {snippet(body)}")


def search_page(code: str) -> list[tuple[str, str]]:
    """The ASX announcements search page (HTML, six months)."""
    url = f"https://www.asx.com.au/asx/v2/statistics/announcements.do?by=asxCode&asxCode={code}&timeframe=D&period=M6"
    status, ctype, body = fetch(url)
    say(f"  {code} search page: {status} {ctype.split(';')[0]} {len(body)} bytes")
    if status != 200:
        return []
    html = body.decode("utf-8", "replace")
    rows = re.findall(r'href="(/asx/v2/statistics/displayAnnouncement\.do\?display=pdf&(?:amp;)?idsId=\d+)"[^>]*>\s*(.*?)\s*<', html, re.S)
    out = [(re.sub(r"\s+", " ", t).strip(), "https://www.asx.com.au" + h.replace("&amp;", "&")) for h, t in rows]
    say(f"      {tally([t for t, _ in out])}")
    show_matches([t for t, _ in out])
    if not out:
        say(f"      no announcement links found; page starts: {snippet(body)}")
    return out


def try_pdf(label: str, url: str) -> None:
    status, ctype, body = fetch(url, "application/pdf,text/html,*/*")
    kind = "PDF" if body.startswith(b"%PDF") else ctype.split(";")[0] or "unknown"
    say(f"  {label}: {status} {kind} {len(body)} bytes")
    if kind != "PDF":
        detail(body)
        links = re.findall(rb'(https?://[^"\']+\.pdf)', body)
        if links:
            say(f"      the page links a PDF: {links[0].decode()[:120]}")
            status, ctype, pdf = fetch(links[0].decode(), "application/pdf")
            say(f"      that PDF: {status} {'PDF' if pdf.startswith(b'%PDF') else ctype} {len(pdf)} bytes")


# ---------- B. managers' holdings files ----------
MANAGER_FILES = [
    ("Vanguard VAS (holdings API)", "https://www.vanguard.com.au/adviser/api/products/adviser/etf/8205/portfolio-holding/stock"),
    ("Vanguard VAS (product page)", "https://www.vanguard.com.au/personal/invest-with-us/etf?portId=8205&tab=portfolio"),
    ("iShares IOZ (holdings CSV)", "https://www.blackrock.com/au/individual/products/251852/ishares-core-sp-asx-200-etf/1478358644060.ajax?fileType=csv&fileName=IOZ_holdings&dataType=fund"),
    ("SPDR STW (daily holdings)", "https://www.ssga.com/au/en_gb/intermediary/library-content/products/fund-data/etfs/apac/holdings-daily-au-en-stw.xlsx"),
    ("Betashares A200 (holdings CSV)", "https://www.betashares.com.au/files/csv/A200_Portfolio_Holdings.csv"),
]


def manager_file(label: str, url: str) -> None:
    status, ctype, body = fetch(url, "*/*")
    kind = ("xlsx" if body.startswith(b"PK") else "PDF" if body.startswith(b"%PDF") else ctype.split(";")[0] or "unknown")
    say(f"  {label}: {status} {kind} {len(body)} bytes")
    if status == 200 and kind not in ("xlsx", "PDF"):
        text = body.decode("utf-8", "replace")
        codes = set(re.findall(r'(?:^|[",\s>])([A-Z][A-Z0-9]{2})(?:\.AX)?(?=[",\s<])', text))
        say(f"      looks like {len(codes)} three-letter codes; starts: {snippet(body, 220)}")
    elif status != 200:
        detail(body)


def main() -> int:
    say(f"Coattail source probe, {datetime.now():%Y-%m-%d %H:%M}, Python {sys.version.split()[0]}")
    say()
    say("A. ASX announcements")
    found: list[tuple[str, str]] = []
    for code in CODES:
        found += [(f"{code}: {h}", k) for h, k in markit(code)]
        legacy(code)
        found += [(f"{code}: {t}", u) for t, u in search_page(code)]
    keys = [(h, k) for h, k in found if (DIRECTOR.search(h) or SUBSTANTIAL.search(h)) and k and not k.startswith("http")]
    if keys:
        say(f"  A data-service document key, for reference ({keys[0][0][:60]}): {keys[0][1][:80]}")
    notice = next(((h, u) for h, u in found if (DIRECTOR.search(h) or SUBSTANTIAL.search(h)) and u.startswith("http")), None)
    if notice:
        h, u = notice
        say(f"  One notice's document ({h[:70]}):")
        try_pdf("    download", u)
    else:
        say("  No notice link found to try downloading.")
    say()
    say("B. Fund managers' holdings files")
    for label, url in MANAGER_FILES:
        manager_file(label, url)
    say()
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say(f"Saved to {LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
