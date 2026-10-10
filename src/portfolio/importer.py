"""Importing a broker's export into a portfolio (docs/kb/features/broker-import.md).

Brokers export either a trade history (each buy and sell, with dates,
prices and brokerage) or a holdings snapshot (what you own now, at an
average cost). Every broker names its columns differently, and the names
change over time, so rather than one parser per broker this reads the
column headings: `FIELDS` lists the names each broker is known to use for
the code, side, units, price, date, brokerage, market and currency.
`BROKERS` adds what's particular to each (how to recognise its file,
CommSec's "B 100 BHP @ 45.00" details, Interactive Brokers' sections and
signed quantities). Nothing is saved until the person has seen a preview
and confirmed it.

Only ASX shares come in: lines on another market or in another currency
are listed and skipped, and a code Sift doesn't know is left unticked for
the person to check. A line already in the portfolio (same code, date,
units and price) isn't added twice."""

from __future__ import annotations

import base64
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from src.portfolio import holdings
from src.portfolio.holdings import HoldingsError

MAX_BYTES = 3_000_000   # a few years of trades is well under this
MAX_ROWS = 5000
HEADER_SCAN = 40        # rows searched for the heading row

# The names brokers give each column, lower case without punctuation.
FIELDS: dict[str, list[str]] = {
    "code": ["code", "asx code", "stock code", "security code", "symbol", "ticker", "instrument code", "instrument",
             "security", "stock", "share code", "epic"],
    "side": ["side", "buy sell", "buysell", "b s", "type", "transaction type", "trade type", "action", "direction",
             "order type", "buy or sell"],
    "units": ["quantity", "qty", "units", "shares", "volume", "filled qty", "fill qty", "filled quantity",
              "avail units", "available units", "holding", "holdings", "number of shares", "no of units", "no of shares",
              "unit", "share quantity"],
    "price": ["price", "trade price", "fill price", "filled price", "execution price", "t price", "unit price",
              "avg price", "average price", "purchase price", "avg fill price", "price per share", "share price"],
    "avg_cost": ["avg cost", "average cost", "cost price", "purchase", "average buy price", "avg buy price",
                 "cost per unit", "average purchase price", "cost basis per share"],
    "total_cost": ["cost", "total cost", "cost base", "book cost", "cost basis", "purchase value", "total purchase"],
    "date": ["date", "trade date", "transaction date", "fill time", "filled time", "executed time", "execution time",
             "order date", "date time", "time", "settlement date", "trade time", "datetime"],
    "brokerage": ["brokerage", "commission", "comm fee", "comm", "fees", "fee", "transaction fee", "brokerage inc gst",
                  "charges", "total fees", "commission and fees", "ib commission"],
    "market": ["market", "exchange", "market code", "listing exchange", "listingexchange", "exchange code", "venue"],
    "currency": ["currency", "ccy", "trade currency", "currency code"],
    "details": ["details", "description", "narrative", "transaction details"],
    "debit": ["debit", "debit amount", "withdrawal"],      # cash out: a buy's cost with brokerage (CommSec)
    "credit": ["credit", "credit amount", "deposit"],      # cash in: a sale's proceeds after brokerage
}
_FIELD_OF = {name: f for f, names in FIELDS.items() for name in names}
ASX_MARKETS = {"asx", "au", "aus", "australia", "xasx", "asx au", "chix", "cxa", "cboe au", "asx24"}


@dataclass(frozen=True)
class Broker:
    broker_id: str
    name: str
    signature: tuple[str, ...] = ()     # headings that mark its file
    note: str = ""                      # how to export, in a line


BROKERS = [
    Broker("commsec", "CommSec", ("details", "debit", "credit", "balance"),
           "Trade history: Accounts, Transactions, download as CSV. Holdings: Portfolio, Holdings, download."),
    Broker("sharesies", "Sharesies", ("instrument code", "market code", "transaction type"),
           "Profile, Reports, Transaction report (CSV)."),
    Broker("cmc", "CMC Invest", ("instrument", "buy sell"), "Reports, Trade history or Holdings, export to CSV or Excel."),
    Broker("nabtrade", "nabtrade", (), "Portfolio, Transaction history, export to CSV."),
    Broker("anz", "ANZ Share Investing", (), "Portfolio, Transaction history, export to CSV."),
    Broker("moomoo", "Moomoo", ("filled qty", "side"), "Orders, history, export to Excel or CSV."),
    Broker("tiger", "Tiger Brokers", ("filled qty",), "Orders or statements, export to Excel or CSV."),
    Broker("ibkr", "Interactive Brokers", ("t price", "comm fee"), "Reports, Statements, Activity or Flex query (Trades), CSV."),
    Broker("etoro", "eToro", ("position id",), "Portfolio, History, Account statement, export to Excel."),
    Broker("selfwealth", "Selfwealth", (), "Portfolio, Trade history, export to CSV."),
    Broker("stake", "Stake", (), "Activity, export to CSV."),
    Broker("superhero", "Superhero", (), "Transactions, export to CSV."),
    Broker("other", "Another broker or a spreadsheet", (), "Any file with a code, units and price column."),
]
BY_ID = {b.broker_id: b for b in BROKERS}

_DETAILS = re.compile(r"\b(B|S|BUY|SELL|BOUGHT|SOLD)\s+([\d,]+(?:\.\d+)?)\s+([A-Z0-9]{2,6})(?:\.AX)?\s*@\s*\$?([\d,]+(?:\.\d+)?)", re.I)
_CODE = re.compile(r"^[A-Z0-9]{2,6}$")


def norm(heading) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(heading or "").lower()).split())


# ---------- reading the file ----------
def read_table(filename: str, content: bytes) -> list[list[str]]:
    """Every row of a CSV or Excel file as text cells."""
    if len(content) > MAX_BYTES:
        raise HoldingsError(f"the file is over {MAX_BYTES // 1_000_000} MB; export a shorter period")
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or content[:2] == b"PK":
        from openpyxl import load_workbook
        try:
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:  # noqa: BLE001 - any unreadable workbook is the person's file, not a crash
            raise HoldingsError("this Excel file couldn't be opened; save it again as .xlsx or CSV") from None
        best: list[list[str]] = []
        for sheet in book.worksheets:  # the sheet with the most filled rows
            rows = [[_cell(v) for v in r] for r in sheet.iter_rows(values_only=True)]
            rows = [r for r in rows if any(c for c in r)]
            if len(rows) > len(best):
                best = rows
        return best[:MAX_ROWS + HEADER_SCAN]
    if name.endswith(".xls"):
        raise HoldingsError("old .xls files can't be read; open it in Excel and save as .xlsx or CSV")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            body = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(body[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(body), dialect)]
    return [r for r in rows if any(c for c in r)][:MAX_ROWS + HEADER_SCAN]


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _ibkr_trades(rows: list[list[str]]) -> list[list[str]]:
    """An Interactive Brokers activity statement holds many sections, each row
    starting with its section name ("Trades,Header,..." then "Trades,Data,...");
    keep the trades, without the two leading cells."""
    trades = [r for r in rows if r and r[0] == "Trades" and len(r) > 2 and r[1] in ("Header", "Data")]
    if not trades:
        return rows
    return [r[2:] for r in trades if r[1] == "Header"][:1] + [r[2:] for r in trades if r[1] == "Data" and r[2:3] != ["Total"]]


def find_header(rows: list[list[str]]) -> int:
    """The heading row: the first of the top rows naming at least two known columns."""
    best, best_hits = 0, 0
    for i, row in enumerate(rows[:HEADER_SCAN]):
        hits = len({_FIELD_OF.get(norm(c)) for c in row} - {None})
        if hits > best_hits:
            best, best_hits = i, hits
        if hits >= 3:
            return i
    return best if best_hits else 0  # nothing recognised: the first row, for the person to choose the columns


def guess_mapping(headings: list[str]) -> dict[str, int]:
    """{field: column index} from the headings; the first match wins."""
    out: dict[str, int] = {}
    for i, h in enumerate(headings):
        f = _FIELD_OF.get(norm(h))
        if f and f not in out:
            out[f] = i
    # A lone "Purchase $" or "Cost" heading in a holdings file is the average cost when there's no price.
    return out


def detect_broker(headings: list[str]) -> str:
    names = {norm(h) for h in headings}
    for b in BROKERS:
        if b.signature and set(b.signature) <= names:
            return b.broker_id
    return "other"


# ---------- reading values ----------
def number(raw) -> Decimal | None:
    s = str(raw or "").strip()
    if not s or s in ("-", "--", "n/a", "N/A"):
        return None
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^\d.]", "", s.replace(",", ""))
    if not s or s.count(".") > 1:
        return None
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y",
                 "%B %d %Y", "%Y/%m/%d", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d")


def parse_when(raw) -> date | None:
    """A date as brokers write it: Australian day first (3/10/2026 is 3
    October), ISO, or with the month in words; any time is ignored."""
    s = str(raw or "").strip()
    if not s:
        return None
    s = re.split(r"[T ](?=\d{1,2}:\d{2})", s)[0]          # drop a time
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s).replace(",", " ").strip()
    s = re.sub(r"\s+", " ", s).split(";")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def clean_code(raw) -> tuple[str | None, str | None]:
    """(ASX code, market a suffix names): "BHP.AX" is BHP; "AAPL.US" is on another market."""
    s = str(raw or "").strip().upper()
    s = re.sub(r"^(ASX|AX)[:.\s]+", "", s)
    m = re.match(r"^([A-Z0-9]{1,6})(?:[.:\s]([A-Z]{1,6}))?$", s)
    if not m:
        return None, None
    code, suffix = m.groups()
    if suffix in (None, "AX", "ASX", "AU"):
        return code, None
    return code, suffix


def side_of(raw) -> str | None:
    s = norm(raw)
    if s in ("b", "buy", "bought", "purchase", "buy to open", "bot", "contract note buy", "market buy", "limit buy") or s.startswith("buy"):
        return "BUY"
    if s in ("s", "sell", "sold", "sld", "sell to close", "market sell", "limit sell") or s.startswith("sell"):
        return "SELL"
    return None


@dataclass
class Line:
    row: int                       # row number in the file, for the person
    code: str | None = None
    side: str | None = None
    units: Decimal | None = None
    price: Decimal | None = None
    when: date | None = None
    brokerage: Decimal = Decimal(0)
    status: str = "new"            # new, duplicate, check, skip
    reason: str | None = None
    include: bool = True
    raw: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {"row": self.row, "code": self.code, "side": self.side, "units": self.units, "price": self.price,
                "date": self.when, "brokerage": self.brokerage, "status": self.status, "reason": self.reason,
                "include": self.include}


def _get(row: list[str], mapping: dict[str, int], f: str) -> str:
    i = mapping.get(f)
    return row[i] if i is not None and i < len(row) else ""


def to_lines(rows: list[list[str]], mapping: dict[str, int], kind: str, holdings_date: date | None, start_row: int) -> list[Line]:
    out = []
    for n, row in enumerate(rows, start=start_row):
        line = Line(row=n, raw=row)
        details = _DETAILS.search(_get(row, mapping, "details")) if "details" in mapping else None
        code, other_market = clean_code(_get(row, mapping, "code"))
        if details and not code:
            code = details.group(3).upper()
        line.code = code
        market = norm(_get(row, mapping, "market"))
        currency = norm(_get(row, mapping, "currency"))
        units = number(_get(row, mapping, "units"))
        if details and units is None:
            units = number(details.group(2))
        if kind == "trades":
            line.side = side_of(_get(row, mapping, "side")) if "side" in mapping else None
            if details and not line.side:
                line.side = side_of(details.group(1))
            if line.side is None and units is not None and "side" not in mapping:
                line.side = "SELL" if units < 0 else "BUY"   # signed quantities (Interactive Brokers)
            line.price = number(_get(row, mapping, "price"))
            if details and line.price is None:
                line.price = number(details.group(4))
            line.when = parse_when(_get(row, mapping, "date"))
            line.brokerage = abs(number(_get(row, mapping, "brokerage")) or Decimal(0))
            if "brokerage" not in mapping and line.price is not None and units:
                # CommSec puts brokerage inside the cash amount: a buy's debit is units x price
                # plus brokerage, a sale's credit is units x price less brokerage.
                gross = abs(units) * line.price
                cash = number(_get(row, mapping, "debit" if line.side == "BUY" else "credit"))
                if cash is not None:
                    fee = (abs(cash) - gross) if line.side == "BUY" else (gross - abs(cash))
                    if Decimal(0) < fee <= max(Decimal(100), gross * Decimal("0.02")):
                        line.brokerage = fee.quantize(Decimal("0.01"))
        else:
            line.side = "BUY"
            line.price = number(_get(row, mapping, "avg_cost")) if "avg_cost" in mapping else number(_get(row, mapping, "price"))
            total = number(_get(row, mapping, "total_cost")) if "total_cost" in mapping else None
            if line.price is None and total is not None and units:
                line.price = (abs(total) / abs(units)).quantize(Decimal("0.0001"))
            line.when = holdings_date
        line.units = abs(units) if units is not None else None
        # What can't come in, and why.
        if not code and not units:
            line.status, line.reason, line.include = "skip", "not a share line (a heading, total or cash entry)", False
        elif other_market or (market and market not in ASX_MARKETS) or (currency and currency not in ("aud", "a")):
            line.status, line.include = "skip", False
            line.reason = f"not on the ASX ({other_market or market.upper() or currency.upper()}): Sift follows ASX shares only"
        elif kind == "trades" and line.side is None:
            line.status, line.reason, line.include = "skip", "not a buy or sell (a dividend, deposit or fee)", False
        elif not code or not _CODE.match(code):
            line.status, line.reason, line.include = "skip", "no ASX code", False
        elif not line.units:
            line.status, line.reason, line.include = "skip", "no units", False
        elif line.price is None or line.price < 0:
            line.status, line.reason, line.include = "skip", "no price", False
        elif line.when is None:
            line.status, line.reason, line.include = "skip", "the date couldn't be read", False
        out.append(line)
    return out


# ---------- preview and import ----------
def _known_codes(session) -> set[str]:
    return {c for (c,) in session.execute(text("SELECT asx_code FROM companies"))}


def _existing(session, portfolio) -> set[tuple]:
    """(code, side, date, units, price) of the portfolio's buys and sales, to
    spot repeats. A sale splits a parcel, so the pieces are added back up."""
    if portfolio is None:
        return set()
    rows = session.execute(text("""
        SELECT asx_code, 'BUY' AS side, buy_date AS day, sum(units) AS units, buy_price AS price
        FROM holdings WHERE portfolio_id = :p GROUP BY asx_code, buy_date, buy_price
        UNION ALL
        SELECT asx_code, 'SELL', sell_date, sum(units), sell_price
        FROM holdings WHERE portfolio_id = :p AND sell_date IS NOT NULL GROUP BY asx_code, sell_date, sell_price"""),
        {"p": portfolio.portfolio_id})
    return {(r.asx_code, r.side, r.day, r.units.normalize(), r.price.normalize()) for r in rows}


def decode(body: dict) -> tuple[str, bytes]:
    try:
        content = base64.b64decode(body.get("content") or "", validate=True)
    except (ValueError, TypeError):
        raise HoldingsError("the file couldn't be read; choose it again") from None
    if not content:
        raise HoldingsError("choose a file exported from your broker")
    return str(body.get("filename") or "import.csv")[:200], content


def preview(session, body: dict, today: date) -> dict:
    """What the file holds and what would be imported: the columns found
    (which the person can change), and each line's status."""
    filename, content = decode(body)
    rows = read_table(filename, content)
    rows = _ibkr_trades(rows)
    h = find_header(rows)
    headings = [c or f"Column {i + 1}" for i, c in enumerate(rows[h])]
    mapping = guess_mapping(headings)
    for f, i in (body.get("mapping") or {}).items():   # the person's corrections
        if f in FIELDS:
            if i is None or i == "":
                mapping.pop(f, None)
            elif 0 <= int(i) < len(headings):
                mapping[f] = int(i)
    broker = body.get("broker") if body.get("broker") in BY_ID else detect_broker(headings)
    # Trades have a date and a buy or sell (or a price); a holdings file has neither date nor side.
    looks_like_trades = "details" in mapping or ("date" in mapping and ("side" in mapping or "price" in mapping))
    kind = body.get("kind") if body.get("kind") in ("trades", "holdings") else ("trades" if looks_like_trades else "holdings")
    holdings_date = parse_when(body.get("holdings_date")) or today
    if holdings_date > today:
        raise HoldingsError("the bought-on date can't be in the future")
    portfolio = holdings.get_portfolio(session, body["portfolio_id"]) if body.get("portfolio_id") else None
    lines = to_lines(rows[h + 1:], mapping, kind, holdings_date, start_row=h + 2)
    known, seen = _known_codes(session), _existing(session, portfolio)
    for ln in lines:
        if ln.status != "new":
            continue
        if ln.when and ln.when > today:
            ln.status, ln.reason, ln.include = "skip", "dated in the future", False
        elif (ln.code, ln.side, ln.when, ln.units.normalize(), ln.price.normalize()) in seen:
            ln.status, ln.reason, ln.include = "duplicate", "already in this portfolio", False
        elif ln.code not in known:
            ln.status, ln.reason, ln.include = "check", "Sift doesn't know this code: tick to import it if it's an ASX code", False
    need = ("code", "units") + (("date",) if kind == "trades" and "details" not in mapping else ())
    missing = [f for f in need if f not in mapping and not (f in ("code", "units") and "details" in mapping)]
    counts = {s: sum(1 for ln in lines if ln.status == s) for s in ("new", "duplicate", "check", "skip")}
    return {"filename": filename, "broker": broker, "broker_note": BY_ID[broker].note, "kind": kind,
            "headings": headings, "mapping": mapping, "missing": missing, "holdings_date": holdings_date,
            "lines": [ln.public() for ln in lines], "counts": counts,
            "brokers": [{"broker_id": b.broker_id, "name": b.name} for b in BROKERS],
            "fields": {f: f.replace("_", " ") for f in FIELDS}}


def apply(session, body: dict, today: date) -> dict:
    """Import the ticked lines into the chosen (or a new) portfolio: buys as
    parcels, then sales in date order against them (first in, first out)."""
    portfolio = None
    if body.get("portfolio_id"):
        portfolio = holdings.get_portfolio(session, body["portfolio_id"])
        if portfolio is None:
            raise HoldingsError("no such portfolio")
    elif body.get("new_portfolio"):
        portfolio = holdings.create_portfolio(session, body["new_portfolio"], body.get("tax_type") or "INDIVIDUAL")
    else:
        raise HoldingsError("choose a portfolio, or name a new one")
    result = preview(session, body | {"portfolio_id": str(portfolio.portfolio_id)}, today)
    if result["missing"]:
        raise HoldingsError(f"choose the {', '.join(result['missing'])} column first")
    ticked = {int(r) for r in body.get("rows") or []}
    chosen = [ln for ln in result["lines"]
              if (ln["row"] in ticked if body.get("rows") is not None else ln["include"]) and ln["status"] in ("new", "check")]
    broker = BY_ID[result["broker"]].name if result["broker"] != "other" else None
    added = sold = 0
    problems = []
    for ln in sorted(chosen, key=lambda x: (x["date"], x["side"] != "BUY", x["row"])):
        try:
            if ln["side"] == "BUY":
                holdings.add_parcel(session, ln["code"], ln["units"], ln["price"], ln["date"], ln["brokerage"],
                                    broker=broker, notes=f"Imported from {result['filename']}, row {ln['row']}", portfolio=portfolio)
                added += 1
            else:
                with session.begin_nested():
                    holdings.sell(session, ln["code"], ln["units"], ln["price"], ln["date"], ln["brokerage"], portfolio=portfolio)
                sold += 1
        except HoldingsError as exc:
            problems.append({"row": ln["row"], "code": ln["code"], "reason": str(exc)})
    return {"portfolio_id": portfolio.portfolio_id, "portfolio": portfolio.name, "bought": added, "sold": sold,
            "problems": problems, "skipped": result["counts"]["skip"] + result["counts"]["duplicate"]}
