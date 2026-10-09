"""Builds the search index (docs/AS_BUILT.md §32): one row in `search_index`
per searchable thing, in five areas that are rebuilt as a unit:

- market:   shares, ETFs and LICs (names, sectors, categories, descriptions, what funds hold)
- coattail: fund managers and the companies they hold (§31)
- personal: watchlists (with their notes), portfolios (with their holdings) and what-if scenarios
- help:     knowledge base articles (web/knowledge.json)
- pages:    Sift's pages, and each model setting in the admin console

When: everything after the nightly run, personal data the moment it's
saved (gui.py's `change()`), help and pages when Sift starts (they change
only with a git pull), and on demand from the admin console or
`python -m src.search.reindex`. Each rebuild is timed in `search_index_runs`.

owner_id is NULL for now: Sift has one user. Personal rows will carry their
owner once Sift has user accounts (multi-user Phase 1), and
the query already shows only NULL or the asker's own rows."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

from sqlalchemy import text

from src.search import embeddings

logger = logging.getLogger(__name__)

AREAS = ("market", "coattail", "personal", "help", "pages")
KNOWLEDGE = Path(__file__).resolve().parents[2] / "web" / "knowledge.json"

# Every table in db/schema.sql is either searched (here, with the area that
# reads it) or deliberately not (EXCLUDED, with why).
# tests/unit/test_search_coverage.py fails when a table is in neither, so a
# new table can't be forgotten: index it (add it to a builder below, or a new
# area with its own builder) or say why not.
SOURCES = {
    "companies": "market", "etf_monthly": "market", "fund_profiles": "market", "fund_holdings": "market",
    "top_holders": "coattail",
    "watchlists": "personal", "watchlist_items": "personal", "portfolios": "personal", "holdings": "personal",
    "scenarios": "personal",
}
EXCLUDED = {
    "daily_prices": "prices: numbers, shown on the company and fund pages that are indexed",
    "financial_reports": "statement figures: numbers, reached through the company",
    "valuation_metrics": "valuation figures: numbers; the latest feed each share's recommendation facet",
    "dividend_payments": "dividend history: numbers, reached through the company",
    "asx_report_loads": "a log of report files loaded",
    "asx_index_returns": "index benchmark returns: no page of their own; shown on fund pages",
    "etf_performance": "fund returns: numbers, reached through the fund",
    "company_insights": "analyst counts and targets: numbers, reached through the company",
    "analyst_ratings": "monthly rating counts: numbers, reached through the company",
    "ui_preferences": "page layout settings",
    "search_index": "the index itself",
    "search_index_runs": "the index's rebuild log",
    "search_queries": "the search log, used to tune ranking (Admin, Search insights)",
    "search_clicks": "clicks on results, used to tune ranking",
    "search_feedback": "thumbs up and down on results, used to tune ranking",
    "search_synonyms": "synonyms that widen searches, managed in Admin",
    "signal_snapshots": "nightly history behind the track record; the track record page is indexed",
    "signal_outcomes": "scored history behind the track record",
    "track_record_monthly": "monthly track record figures",
}

_INSERT = text("""
    INSERT INTO search_index (doc_id, area, kind, owner_id, code, title, subtitle, body, url, facets, rank_boost, content_hash, search_vector)
    VALUES (:doc_id, :area, :kind, :owner_id, :code, :title, :subtitle, :body, :url, CAST(:facets AS JSONB), :rank_boost, :content_hash,
            setweight(to_tsvector('simple', coalesce(:code, '')), 'A')
            || setweight(to_tsvector('english', :title), 'A')
            || setweight(to_tsvector('english', coalesce(:subtitle, '')), 'B')
            || setweight(to_tsvector('english', coalesce(:body, '')), 'C'))
    ON CONFLICT (doc_id) DO NOTHING
""")

PAGES = [
    ("Dashboard", "#/", "Home: what needs attention, what changed, biggest movers, top opportunities, your ETFs and LICs, and the track record."),
    ("Screener", "#/screener", "Every company Sift values, with its score, margin of safety, the four value tests and a suggested action."),
    ("ETFs", "#/etfs", "Every ETF on the ASX with fee, size, yield and returns."),
    ("LICs", "#/lics", "Listed investment companies and trusts, priced against their net tangible assets."),
    ("Watchlists", "#/watchlists", "Your named lists of companies, ETFs and LICs to follow, with notes and triggers."),
    ("Portfolios", "#/portfolios", "Your portfolios, holdings, trades, CGT and the tax report."),
    ("Track record", "#/track-record", "Whether Sift's suggestions have worked: accuracy by action, what you missed, what now."),
    ("Coattail", "#/coattail", "Follow the smart money: which fund managers hold the screener's companies and what they're buying and selling."),
    ("Help", "#/help", "The knowledge base: every term and screen explained."),
    ("Model and rules", "#/admin", "Admin console: every setting and formula behind Sift's valuations, tests and actions."),
    ("What-if scenarios", "#/admin/scenarios", "Try changed settings against today's data without touching the live ones."),
]


def _doc(area, kind, doc_id, title, url, code=None, subtitle=None, body=None, facets=None, rank_boost=0.0, owner_id=None):
    return {"doc_id": f"{kind}:{doc_id}", "area": area, "kind": kind, "owner_id": owner_id, "code": code, "title": title,
            "subtitle": subtitle, "body": body, "url": url, "facets": json.dumps(facets or {}), "rank_boost": rank_boost,
            "content_hash": embeddings.content_hash(title, subtitle, body)}


class _Context:
    """What several areas need, loaded once per rebuild."""

    def __init__(self, session, today: date):
        self.session, self.today = session, today
        self._rows = None

    @property
    def rows(self):
        if self._rows is None:
            from src.screening.enriched import load_universe
            self._rows = load_universe(self.session, self.today).rows
        return self._rows


def market_docs(ctx: _Context) -> list[dict]:
    from src.etf.views import etf_rows

    session = ctx.session
    extra = {code: (industry, summary) for code, industry, summary in session.execute(text(
        "SELECT asx_code, industry, business_summary FROM companies WHERE security_type = 'SHARE'"))}
    docs = []
    for r in ctx.rows:
        code = r["asx_code"]
        industry, summary = extra.get(code, (None, None))
        docs.append(_doc("market", "share", code, r["company_name"] or code, f"#/company/{code}", code=code,
                         subtitle=" · ".join(x for x in ("Share", r.get("sector"), industry) if x),
                         body=summary, facets={"sector": r.get("sector"), "recommendation": r.get("action"), "codes": [code]},
                         rank_boost=0.2))
    profiles = dict(session.execute(text("""
        SELECT c.asx_code, p.description FROM fund_profiles p JOIN companies c USING (company_id) WHERE p.description IS NOT NULL""")).all())
    holds: dict[str, list[str]] = {}  # what each fund holds: "apple" finds the ETFs holding Apple
    for code, name in session.execute(text("""
            SELECT c.asx_code, f.name FROM fund_holdings f JOIN companies c USING (company_id) WHERE f.name IS NOT NULL""")):
        holds.setdefault(code, []).append(name)
    for kind in ("ETF", "LIC"):
        for r in etf_rows(session, ctx.today, {}, kind):
            code = r["asx_code"]
            docs.append(_doc("market", kind.lower(), code, r["company_name"] or code, f"#/{kind.lower()}/{code}", code=code,
                             subtitle=" · ".join(x for x in (kind, r.get("category"), r.get("issuer")) if x),
                             body=" ".join(x for x in (r.get("benchmark"), profiles.get(code), " ".join(holds.get(code, []))) if x) or None,
                             facets={"category": r.get("category"), "codes": [code]}))
    return docs


def coattail_docs(ctx: _Context) -> list[dict]:
    from src.coattail.views import holdings

    data = holdings(ctx.session, ctx.rows, {})
    managers: dict[str, dict] = {}
    for m in data["holdings"]:
        g = managers.setdefault(m["manager_id"], {"name": m["manager"], "holders": set(), "codes": set()})
        g["holders"].add(m["holder"])
        g["codes"].add(m["asx_code"])
    docs = []
    for mid, g in managers.items():
        codes = sorted(g["codes"])
        names = [data["companies"][c]["company_name"] or c for c in codes]
        docs.append(_doc("coattail", "manager", mid, g["name"], f"#/coattail/{mid}",
                         subtitle=f"Fund manager · holds {len(codes)} screener compan{'y' if len(codes) == 1 else 'ies'}",
                         body=" ".join(sorted(g["holders"])) + " " + " ".join(f"{c} {n}" for c, n in zip(codes, names)),
                         facets={"codes": codes}))
    return docs


def personal_docs(ctx: _Context) -> list[dict]:
    from src.portfolio import cgt
    from src.portfolio.holdings import list_portfolios
    from src.watchlist import lists

    session = ctx.session
    names = dict(session.execute(text("SELECT asx_code, company_name FROM companies")).all())
    docs = []
    by_list: dict = {}
    for item, code, _ in lists.entries(session):
        by_list.setdefault(item.watchlist_id, []).append((code, item.note))
    for w in lists.list_watchlists(session):
        entries = by_list.get(w.watchlist_id, [])
        codes = [c for c, _ in entries]
        docs.append(_doc("personal", "watchlist", str(w.watchlist_id), w.name, f"#/watchlist/{w.watchlist_id}",
                         subtitle=f"Watchlist · {len(codes)} item{'' if len(codes) == 1 else 's'}",
                         body=" ".join(f"{c} {names.get(c) or ''} {note or ''}" for c, note in entries) or None,
                         facets={"codes": codes}))
    held = {}
    for pid, code in session.execute(text("SELECT DISTINCT portfolio_id, asx_code FROM holdings WHERE sell_date IS NULL")):
        held.setdefault(pid, []).append(code)
    for p in list_portfolios(session):
        codes = sorted(held.get(p.portfolio_id, []))
        archived = " · archived" if p.archived_at else ""
        docs.append(_doc("personal", "portfolio", str(p.portfolio_id), p.name, f"#/portfolio/{p.portfolio_id}",
                         subtitle=f"Portfolio · {cgt.TAX_TYPE_LABELS[p.tax_type]}{archived}",
                         body=" ".join(f"{c} {names.get(c) or ''}" for c in codes) or None, facets={"codes": codes}))
    for sid, name, notes in session.execute(text("SELECT scenario_id, name, notes FROM scenarios")):
        docs.append(_doc("personal", "scenario", str(sid), name, f"#/admin/scenario/{sid}", subtitle="What-if scenario", body=notes))
    return docs


def help_docs(ctx: _Context) -> list[dict]:
    kb = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    topics = {c["id"]: c["name"] for c in kb["categories"]}
    return [_doc("help", "help", e["id"], e["title"], f"#/help/{e['id']}", subtitle=e.get("definition"),
                 body=" ".join([*e.get("aliases", []), *e.get("labels", []), *e.get("body", [])]) or None,
                 facets={"topic": topics.get(e["category"])}) for e in kb["entries"]]


def page_docs(ctx: _Context) -> list[dict]:
    from src.settings import GROUPS, SETTINGS

    groups = dict(GROUPS)
    docs = [_doc("pages", "page", url.strip("#/").replace("/", "-") or "dashboard", title, url, subtitle="Page", body=body, rank_boost=0.3)
            for title, url, body in PAGES]
    docs += [_doc("pages", "setting", s.key, s.label, "#/admin", subtitle=f"Setting · {groups.get(s.group, s.group)}",
                  body=f"{s.formula}. Used in: {s.used_in}.") for s in SETTINGS]
    return docs


BUILDERS = {"market": market_docs, "coattail": coattail_docs, "personal": personal_docs, "help": help_docs, "pages": page_docs}


def reindex(session, areas=AREAS, trigger: str = "manual", today: date | None = None) -> dict[str, int]:
    """Rebuild these areas (all by default) and record each rebuild. The
    caller commits. Returns the number of items indexed per area."""
    ctx = _Context(session, today or date.today())
    counts = {}
    for area in areas:
        started = time.monotonic()
        docs = BUILDERS[area](ctx)
        # Keep each unchanged row's embedding across the rebuild: only new or changed text is embedded again.
        kept = session.execute(text("""
            SELECT doc_id, content_hash, embedding, embedding_model FROM search_index
            WHERE area = :a AND embedding IS NOT NULL"""), {"a": area}).all()
        session.execute(text("DELETE FROM search_index WHERE area = :a"), {"a": area})
        if docs:
            session.execute(_INSERT, docs)
            if kept:
                session.execute(text("""
                    UPDATE search_index SET embedding = :e, embedding_model = :m WHERE doc_id = :d AND content_hash = :h"""),
                    [{"d": d, "h": h, "e": e, "m": m} for d, h, e, m in kept])
        seconds = round(time.monotonic() - started, 2)
        session.execute(text("INSERT INTO search_index_runs (area, trigger, items, seconds) VALUES (:a, :t, :n, :s)"),
                        {"a": area, "t": trigger, "n": len(docs), "s": seconds})
        counts[area] = len(docs)
        logger.info("Search index: %s rebuilt, %d items in %.2fs (%s)", area, len(docs), seconds, trigger)
    embedder = embeddings.get_embedder()
    if embedder is not None:
        n = embeddings.embed_missing(session, embedder, areas)
        logger.info("Search index: %d rows embedded with %s", n, embedder.name)
    if trigger == "nightly":
        from src.search.learning import prune
        prune(session)
    return counts


def status(session) -> dict:
    """Items per area and each area's latest rebuild, for the admin console."""
    items = dict(session.execute(text("SELECT area, count(*) FROM search_index GROUP BY area")).all())
    last = {r["area"]: dict(r) for r in session.execute(text("""
        SELECT DISTINCT ON (area) area, trigger, items, seconds, finished_at FROM search_index_runs
        ORDER BY area, finished_at DESC""")).mappings()}
    typo = bool(session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).first())
    return {"typo_tolerance": typo, "ai": embeddings.status(session),
            "areas": [{"area": a, "items": items.get(a, 0), "last": last.get(a)} for a in AREAS]}
