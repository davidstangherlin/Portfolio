"""Reading ASX director and substantial holder notices (docs/kb/features/coattail.md).

The notices are fixed forms, so their PDFs' text carries the same labels
every time, though the layout (and so the order the text comes out in)
varies from company to company:

- Appendix 3Y, "Change of Director's Interest Notice": one Part 1 per
  director, with labels such as "Date of change", "Number acquired",
  "Number disposed", "Value/Consideration" and "Nature of change".
- Form 603 (becoming a substantial holder), 604 (change in substantial
  holding) and 605 (ceasing to be one): the holder's name, the date, and
  the voting power (% of votes) before and after.

The readers take a value as the text between its label and the next
known label, then pick numbers out of it. Anything they can't find stays
None and the notice is marked "partial", so the page shows the PDF link
rather than a wrong number. READER_VERSION goes up whenever the reading
changes, so `python -m src.coattail.notices --reread` can redo old notices."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

READER_VERSION = 1

# ---------- titles ----------
# What the user follows (2026-10-09): titles containing "Becoming",
# "Change in" or "Ceasing" (substantial holders), plus director trades,
# which ASX titles "Change of Director's Interest Notice" (Appendix 3Y).
KINDS = {
    "DIRECTOR": "Director trade",
    "SUBSTANTIAL_NEW": "Became a substantial holder",
    "SUBSTANTIAL_CHANGE": "Changed a substantial holding",
    "SUBSTANTIAL_CEASE": "Ceased to be a substantial holder",
}
_TITLE_RULES = [
    ("DIRECTOR", re.compile(r"change of director'?s'? interest|appendix 3y", re.I)),
    ("SUBSTANTIAL_NEW", re.compile(r"\bbecoming\b", re.I)),
    ("SUBSTANTIAL_CEASE", re.compile(r"\bceasing\b", re.I)),
    ("SUBSTANTIAL_CHANGE", re.compile(r"\bchange in\b", re.I)),
]
_SUBSTANTIAL_WORDS = re.compile(r"substantial|form 60[345]|\bholder|\bholding|\bshareholder", re.I)


def classify(headline: str) -> str | None:
    """The kind of notice a headline is, or None if it isn't one Sift follows.
    "Becoming", "Change in" and "Ceasing" count when the title is about a
    substantial holding (so "Change in Chief Executive" doesn't)."""
    for kind, rule in _TITLE_RULES:
        if rule.search(headline or ""):
            if kind != "DIRECTOR" and not _SUBSTANTIAL_WORDS.search(headline):
                continue
            return kind
    return None


def holder_from_headline(headline: str) -> str | None:
    """The holder a title names: "Change in substantial holding from Vanguard"."""
    m = re.search(r"\b(?:from|for|by|-|:)\s+([A-Z][^()]{1,120}?)\s*(?:\(.*\))?\s*$", headline or "")
    if m and not re.search(r"substantial|holder|holding", m.group(1), re.I):
        return m.group(1).strip(" .,")
    return None


_GROUP_WORDS = re.compile(
    r"\s*(\(.*?\)|,?\s*(and|&)\s+(its|their)\s+(related bodies corporate|controlled entities|subsidiaries|associates|affiliates)\b.*"
    r"|,?\s*(and|&)\s+associates\b.*|,?\s*on behalf of\b.*|,?\s*as (trustee|responsible entity)\b.*|,?\s*group of companies\b.*)",
    re.I)


def holder_group(holder: str | None) -> str | None:
    """A substantial holder's name without the legal tail: "Perpetual Limited
    and its related bodies corporate" is "Perpetual Limited"."""
    if not holder:
        return holder
    short = _GROUP_WORDS.sub("", holder).strip(" ,;")
    return short or holder


# ---------- PDF text ----------
def pdf_text(content: bytes) -> str:
    """All the text in a PDF, page after page."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _flat(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text)


_NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])|(?<![\w.,])\d+(?:\.\d+)?(?![\d,]*\d)")
_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(m(?:illion)?\b|k\b)?", re.I)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")


def _decimal(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def first_number(s: str | None) -> Decimal | None:
    """The first number in a field; "Nil", "N/A" or "-" alone are 0."""
    if not s:
        return None
    if re.fullmatch(r"\s*(nil|none|n/?a|-|0)\s*\.?\s*", s, re.I):
        return Decimal(0)
    m = _NUMBER.search(s)
    return _decimal(m.group(0)) if m else None


def money(s: str | None) -> tuple[Decimal | None, bool]:
    """(dollars, per_share): the first dollar amount and whether it's a price
    per share ("$4.50 per share") rather than a total."""
    if not s:
        return None, False
    m = _MONEY.search(s)
    if not m:
        return None, False
    value = _decimal(m.group(1))
    if value is not None and m.group(2):
        value *= Decimal(1_000_000) if m.group(2).lower().startswith("m") else Decimal(1000)
    tail = s[m.end():m.end() + 40]
    per_share = bool(re.match(r"\s*(per|each|/|a)\s*(ordinary\s*)?(share|security|unit)", tail, re.I)) or bool(
        re.search(r"(average|avg\.?|weighted)\s*(price)?\s*(of\s*)?$", s[:m.start()], re.I))
    return value, per_share


def parse_date(s: str | None) -> date | None:
    """A date written as 5/09/2026, 05-09-26, 5 September 2026 or 5 Sep 2026."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", s)
    if m:
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)[:3] if fmt.endswith('%b %Y') else m.group(2)} {m.group(3)}", fmt).date()
            except ValueError:
                continue
    return None


def _fields(text: str, labels: list[tuple[str, str]]) -> dict[str, str]:
    """{name: the text between this label and the next label found}."""
    hits = []
    for name, pattern in labels:
        m = re.search(pattern, text, re.I)
        if m:
            hits.append((m.start(), m.end(), name))
    hits.sort()
    out = {}
    for i, (_, end, name) in enumerate(hits):
        stop = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        out[name] = text[end:stop]
    return out


def _phrase(words: str) -> re.Pattern:
    """A sentence from the form, however the PDF spaced or broke it."""
    return re.compile(r"\s*".join(re.escape(w).replace(r"\-", r"-\s*") for w in words.split()), re.I)


# The form's own guidance, printed beside the boxes. It must go before a
# value is read: the "Nature of change" example names every kind of change.
_GUIDANCE = [_phrase(g) for g in (
    "Example: on-market trade, off-market trade, exercise of options, issue of securities under dividend reinvestment plan, participation in buy-back",
    "Note: If consideration is non-cash, provide details and estimated valuation",
    "Note: Provide details of the circumstances giving rise to the relevant interest.",
    "Note: Details are only required for a contract in relation to which the interest has changed",
    "(including registered holder)",
    "(if applicable)",
    "(if issued securities)",
)]


def _clean(value: str | None, limit: int = 300) -> str | None:
    if value is None:
        return None
    for g in _GUIDANCE:
        value = g.sub(" ", value)
    # Backstop for a reworded example: everything from "Example:" to its last item.
    value = re.sub(r"(?is)example\s*:.{0,300}?participation\s+in\s+buy\s*-?\s*back", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" :-\n")
    return value[:limit] or None


# ---------- Appendix 3Y ----------
_3Y_LABELS = [
    ("entity", r"name of entity"),
    ("abn", r"\bABN\b"),
    ("director", r"name of director"),
    ("last_notice", r"date of last notice"),
    ("part1", r"part 1\s*-?\s*change of director'?s'? relevant interests"),
    ("interest", r"direct or indirect\s+interest"),
    ("indirect", r"nature of indirect interest"),
    ("change_date", r"date of change"),
    ("held_before", r"no\.? of securities held prior to change"),
    ("class", r"\bclass\b(?!\s+of)"),
    ("acquired", r"number acquired"),
    ("disposed", r"number disposed"),
    ("value", r"value\s*/\s*consideration"),
    ("held_after", r"no\.? of securities held after change"),
    ("nature", r"nature of change"),
    ("part2", r"part 2\s*-?\s*change of director'?s'? interests in contracts"),
]


@dataclass
class DirectorTrade:
    director: str | None = None
    interest: str | None = None
    change_date: date | None = None
    security_class: str | None = None
    acquired: Decimal | None = None
    disposed: Decimal | None = None
    consideration: Decimal | None = None
    price: Decimal | None = None
    held_after: str | None = None
    nature: str | None = None
    nature_kind: str = "OTHER"
    direction: str = "NONE"

    @property
    def complete(self) -> bool:
        return self.director is not None and (self.acquired is not None or self.disposed is not None)


def nature_kind(nature: str | None) -> str:
    """What kind of change: an on-market trade is the one that shows conviction."""
    n = (nature or "").lower()
    if re.search(r"off[- ]?market", n):
        return "OFF_MARKET"
    if re.search(r"on[- ]?market|market purchase|purchased on (the )?asx|bought on (the )?asx", n):
        return "ON_MARKET"
    if re.search(r"exercise|conversion|vesting|vested", n):
        return "EXERCISE"
    if re.search(r"dividend reinvestment|\bdrp\b|reinvestment plan", n):
        return "DRP"
    if re.search(r"issue|grant|allot|placement|entitlement|share purchase plan|\bspp\b|performance rights|incentive|remuneration", n):
        return "ISSUE"
    return "OTHER"


def direction(acquired: Decimal | None, disposed: Decimal | None) -> str:
    a, d = acquired or 0, disposed or 0
    if a and d:
        return "MIXED"
    return "BUY" if a else "SELL" if d else "NONE"


def read_3y(text: str) -> tuple[str | None, list[DirectorTrade]]:
    """(entity name, one trade per director's Part 1) from an Appendix 3Y."""
    text = _flat(text)
    starts = [m.start() for m in re.finditer(r"name of director", text, re.I)] or [0]
    entity = _clean(_fields(text, _3Y_LABELS).get("entity"), 255)
    trades = []
    for i, start in enumerate(starts):
        chunk = text[max(0, start - 1 if i else 0):starts[i + 1] if i + 1 < len(starts) else len(text)]
        f = {k: _clean(v) for k, v in _fields(chunk, _3Y_LABELS).items()}
        t = DirectorTrade(director=(f.get("director") or "")[:160] or None, change_date=parse_date(f.get("change_date")),
                          security_class=(f.get("class") or "")[:160] or None, acquired=first_number(f.get("acquired")),
                          disposed=first_number(f.get("disposed")), held_after=f.get("held_after"),
                          nature=f.get("nature"))
        interest = (f.get("interest") or "").lower()
        t.interest = ("both" if "direct" in interest.replace("indirect", "") and "indirect" in interest
                      else "indirect" if "indirect" in interest else "direct" if "direct" in interest else None)
        value, per_share = money(f.get("value"))
        units = t.acquired or t.disposed
        if value is not None:
            if per_share:
                t.price = value
                t.consideration = (value * units).quantize(Decimal("0.01")) if units else None
            else:
                t.consideration = value
                t.price = (value / units).quantize(Decimal("0.0001")) if units else None
        t.nature_kind = nature_kind(t.nature)
        t.direction = direction(t.acquired, t.disposed)
        if t.director or t.acquired is not None or t.disposed is not None:
            trades.append(t)
    return entity, trades


# ---------- forms 603, 604, 605 ----------
@dataclass
class SubstantialHolding:
    holder: str | None = None
    entity: str | None = None
    event_date: date | None = None
    previous_pct: Decimal | None = None
    present_pct: Decimal | None = None
    votes: Decimal | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.holder is not None and self.event_date is not None and (self.present_pct is not None)


_EVENT = {
    "SUBSTANTIAL_NEW": r"became a substantial holder on",
    "SUBSTANTIAL_CHANGE": r"change in the interests of the\s+substantial holder on",
    "SUBSTANTIAL_CEASE": r"ceased to be a substantial holder on",
}


def read_substantial(text: str, kind: str) -> SubstantialHolding:
    text = _flat(text)
    out = SubstantialHolding()
    m = re.search(r"to\s+company name\s*/\s*scheme\s*(.+?)\s*(?:ACN|ARSN|ABN)\b", text, re.I | re.S)
    if m:
        out.entity = _clean(m.group(1), 255)
    m = re.search(r"details of substantial holder\s*(?:\(\d\))?\s*name\s*(.+?)\s*(?:ACN|ARSN|ABN)\s*/?", text, re.I | re.S)
    if m:
        out.holder = _clean(m.group(1), 255)
    m = re.search(_EVENT[kind] + r"\s*(.{0,40})", text, re.I | re.S)
    if m:
        out.event_date = parse_date(m.group(1))
    if kind == "SUBSTANTIAL_CEASE":
        out.present_pct = Decimal(0)  # below 5%: the form doesn't say how far
        return out
    # Voting power sits in part 2, before the details of relevant interests in part 3.
    m = re.search(r"2\.\s*(details of voting power|previous and present voting power)(.+?)(?:\n\s*3\.|details of relevant interests|changes in relevant interests)",
                  text, re.I | re.S)
    section = m.group(2) if m else ""
    pcts = [_decimal(p) for p in _PCT.findall(section)]
    pcts = [p for p in pcts if p is not None and p <= 100]
    numbers = [n for n in (_decimal(x) for x in _NUMBER.findall(_PCT.sub(" ", section))) if n is not None and n >= 1000]
    if kind == "SUBSTANTIAL_NEW" and pcts:
        out.present_pct = pcts[0]
        out.votes = numbers[-1] if numbers else None
    elif kind == "SUBSTANTIAL_CHANGE" and len(pcts) >= 2:
        out.previous_pct, out.present_pct = pcts[0], pcts[1]
        out.votes = numbers[-1] if numbers else None
    elif kind == "SUBSTANTIAL_CHANGE" and pcts:
        out.present_pct = pcts[-1]
        out.notes.append("only one voting power figure found")
    return out
