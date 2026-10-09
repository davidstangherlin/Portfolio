"""Searching the index (docs/AS_BUILT.md §32): ranked matches with a
highlighted snippet, and tick-box facets with counts.

Matching: every word of the query, each as a word start ("wes" finds
Wesfarmers), against code, title, subtitle and body (weighted in that
order); an exact code or title ranks first. With pg_trgm, when the words
find little (fewer than TYPO_WHEN results) a near miss on a title is tried
as well, so "vangaurd" finds Vanguard without "franking" also finding
Franklin. Queries under five letters skip it: trigrams of short words
match too much.

Facets are counted the usual way for tick boxes: each group's counts allow
for the boxes ticked in the other groups but not its own, so ticking one
box never hides its neighbours."""

from __future__ import annotations

import re

from sqlalchemy import text

from src.accounts import current_user_id
from src.search import embeddings, learning

CANDIDATES = 400
SYNONYM_SCORE = 0.9     # a match through a synonym ranks just below the same match on the words typed
SEMANTIC_WEIGHT = 2.0   # meaning similarity (0 to 1) x this; an exact title is 6, an exact code 10
TYPO_WHEN = 5         # fewer word matches than this: try near misses too
TYPO_MIN_LETTERS = 5
TYPO_SIMILARITY = 0.42  # pg_trgm word_similarity; swapped letters (vangaurd) score about 0.44
SHOWN = 100
KIND_LABELS = {"share": "Shares", "etf": "ETFs", "lic": "LICs", "manager": "Fund managers", "watchlist": "Watchlists",
               "portfolio": "Portfolios", "scenario": "What-if scenarios", "help": "Help articles", "page": "Pages", "setting": "Settings",
               "devkb": "Developer articles"}
GROUPS = ("type", "sector", "recommendation", "mine", "topic")  # the tick-box groups, top to bottom
HL_START, HL_END = "\u0002", "\u0003"  # snippet highlight markers; the page turns them into <mark>


STOP = {"a", "an", "and", "the", "of", "in", "on", "for", "to", "is", "by", "with", "at", "or", "my"}


def words(q: str) -> list[str]:
    """The query's words, lower case, letters and digits only (safe in a tsquery), without little words."""
    found = re.findall(r"[a-z0-9]+", (q or "").lower())
    return [w for w in found if w not in STOP] or found


def tsquery_sql(n: int) -> str:
    """Each word matches as itself, stemmed ("dividends" finds dividend), or
    as the start of a word ("wes" finds Wesfarmers), and every word must
    match. Stems aren't used as prefixes: "franking" stems to "frank",
    which as a prefix would find Franklin."""
    return " && ".join(f"(to_tsquery('english', :w{i}) || to_tsquery('simple', :p{i}))" for i in range(n))


def _typo_tolerant(session) -> bool:
    return bool(session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).first())


def _sql(typo: bool, n: int) -> str:
    """Word matches for n words, or (typo) near misses on the title instead."""
    near = "word_similarity(:plain, lower(s.title))" if typo else "0"
    match = f"{near} > {TYPO_SIMILARITY}" if typo else "(s.search_vector @@ q.query OR lower(s.code) = :plain)"
    return f"""
        WITH q AS (SELECT {tsquery_sql(n)} AS query)
        SELECT s.doc_id, s.kind, s.code, s.title, s.subtitle, s.url, s.facets,
               ts_headline('english', coalesce(nullif(s.body, ''), s.subtitle, ''), q.query,
                           'StartSel={HL_START}, StopSel={HL_END}, MaxWords=28, MinWords=10, ShortWord=2, MaxFragments=1') AS snippet,
               (CASE WHEN lower(s.code) = :plain THEN 10 WHEN lower(s.title) = :exact THEN 6
                     WHEN lower(s.title) LIKE :exact || '%' THEN 2 ELSE 0 END)
               + ts_rank_cd(s.search_vector, q.query) * 4 + {near} + s.rank_boost AS score
        FROM search_index s, q
        WHERE (s.owner_id IS NULL OR s.owner_id = :owner) AND (s.audience = 'all' OR :admin)
          AND (s.area = 'devkb') = :devkb
          AND {match}
        ORDER BY score DESC, s.title
        LIMIT {CANDIDATES}
    """


def _is_admin(session, user_id) -> bool:
    """Admin-only rows (the developer knowledge base, §36) are for admins."""
    return bool(session.execute(text("SELECT role = 'admin' FROM users WHERE user_id = :u"), {"u": user_id}).scalar())


def _mine_codes(session, owner_id) -> tuple[set[str], set[str]]:
    """What this person holds and watches."""
    held = {c for (c,) in session.execute(text("""
        SELECT DISTINCT h.asx_code FROM holdings h JOIN portfolios p USING (portfolio_id)
        WHERE h.sell_date IS NULL AND p.owner_id = :o"""), {"o": owner_id})}
    watched = {c for (c,) in session.execute(text("""
        SELECT DISTINCT c.asx_code FROM watchlist_items i JOIN companies c USING (company_id)
        JOIN watchlists w USING (watchlist_id) WHERE w.owner_id = :o"""), {"o": owner_id})}
    return held, watched


def _values(row: dict) -> dict[str, list[str]]:
    """Which box in each group a result counts towards."""
    f = row["facets"] or {}
    codes = set(f.get("codes") or [])
    mine = [label for label, flag in (("Held", codes & row["_held"]), ("On a watchlist", codes & row["_watched"])) if flag]
    if row["kind"] in ("watchlist", "portfolio"):
        mine.append("My lists")
    return {"type": [KIND_LABELS.get(row["kind"], row["kind"])],
            "sector": [x for x in (f.get("sector"), f.get("category")) if x],
            "recommendation": [f["recommendation"]] if f.get("recommendation") else [],
            "mine": mine,
            "topic": [f["topic"]] if f.get("topic") else []}


def _word_matches(session, ws: list[str], exact: str, owner_id, typo: bool, devkb: bool = False) -> list[dict]:
    params = {"plain": " ".join(ws), "exact": exact, "owner": owner_id, "admin": _is_admin(session, owner_id), "devkb": devkb}
    for i, w in enumerate(ws):
        params[f"w{i}"], params[f"p{i}"] = w, f"{w}:*"
    rows = [dict(r) for r in session.execute(text(_sql(False, len(ws))), params).mappings()]
    if typo and len(rows) < TYPO_WHEN and len(params["plain"]) >= TYPO_MIN_LETTERS:
        seen = {r["doc_id"] for r in rows}
        rows += [dict(r) for r in session.execute(text(_sql(True, len(ws))), params).mappings() if r["doc_id"] not in seen]
    return rows


_BY_ID = text("""
    SELECT doc_id, kind, code, title, subtitle, url, facets, left(coalesce(nullif(body, ''), subtitle, ''), 220) AS snippet, rank_boost AS score
    FROM search_index WHERE doc_id = ANY(:ids) AND (audience = 'all' OR :admin) AND (area = 'devkb') = :devkb
""")


SCOPES = ("all", "devkb")  # everything a person may see, or (admins only) the developer knowledge base


def search(session, q: str, selected: dict[str, list[str]] | None = None, owner_id=None, log: bool = False,
           query_id: int | None = None, scope: str = "all") -> dict:
    """Results for `q`, narrowed by the ticked boxes in `selected` ({group: [values]}),
    with every group's boxes and counts.

    Ranking: word matches (and synonyms of the words, scored at 90%), then,
    when an embedder is on, meaning matches blended in (SEMANTIC_WEIGHT x
    similarity, added to a word match's score or as the score of a row only
    meaning found), then what clicks and votes have taught for these words
    (src/search/learning.py). `log` records the search (once per search,
    not per tick box); the result carries its query_id for clicks. Personal
rows and "Mine" are the current user's unless `owner_id` says otherwise.

    `scope` "all" searches everything except the developer knowledge base;
    "devkb" searches only it, and finds nothing for someone who isn't an
    admin (§36)."""
    selected = {g: set(v) for g, v in (selected or {}).items() if g in GROUPS and v}
    owner_id = owner_id or current_user_id(session)
    devkb = scope == "devkb"
    ws = words(q) if not devkb or _is_admin(session, owner_id) else []
    typo = _typo_tolerant(session)
    embedder = embeddings.get_embedder()
    if not ws:
        return {"q": q, "total": 0, "results": [], "facets": [], "typo_tolerance": typo, "ai": embedder is not None}
    norm = " ".join(ws)
    exact = re.sub(r"\s+", " ", (q or "").strip().lower()).replace("%", "").replace("_", "")
    found: dict[str, dict] = {}
    for i, variant in enumerate(learning.variants(session, ws)):
        for r in _word_matches(session, variant, exact if i == 0 else " ".join(variant), owner_id, typo, devkb):
            r["score"] = float(r["score"]) * (1 if i == 0 else SYNONYM_SCORE)
            if r["doc_id"] not in found or r["score"] > found[r["doc_id"]]["score"]:
                found[r["doc_id"]] = r
    if embedder is not None:
        meaning = dict(embeddings.semantic_matches(session, embedder, q, owner_id))
        missing = [d for d in meaning if d not in found]
        if missing:
            for r in session.execute(_BY_ID, {"ids": missing, "admin": _is_admin(session, owner_id), "devkb": devkb}).mappings():
                found[r["doc_id"]] = dict(r) | {"score": float(r["score"])}
        for d, sim in meaning.items():
            if d in found:
                found[d]["score"] += SEMANTIC_WEIGHT * sim
    learned = learning.boosts(session, norm)
    for d, b in learned.items():
        if d in found:
            found[d]["score"] += b
    rows = sorted(found.values(), key=lambda r: (-r["score"], r["title"]))
    held, watched = _mine_codes(session, owner_id)
    for r in rows:
        r["_held"], r["_watched"] = held, watched
        r["_values"] = _values(r)

    def passes(r, skip=None):
        return all(set(r["_values"][g]) & want for g, want in selected.items() if g != skip)

    facets = []
    for g in GROUPS:
        counts: dict[str, int] = {}
        for r in rows:
            if passes(r, skip=g):
                for v in r["_values"][g]:
                    counts[v] = counts.get(v, 0) + 1
        order = list(KIND_LABELS.values()) if g == "type" else None
        boxes = sorted(counts.items(), key=lambda kv: (order.index(kv[0]) if order and kv[0] in order else 99, -kv[1], kv[0]))
        if boxes:
            facets.append({"group": g, "boxes": [{"value": v, "count": n, "ticked": v in selected.get(g, ())} for v, n in boxes]})
    shown = [r for r in rows if passes(r)]
    votes = learning.my_votes(session, norm, owner_id)
    if log:
        query_id = learning.log_query(session, q, norm, len(rows), owner_id)
    results = [{"doc_id": r["doc_id"], "kind": r["kind"], "type": KIND_LABELS.get(r["kind"], r["kind"]), "code": r["code"],
                "title": r["title"], "subtitle": r["subtitle"], "url": r["url"], "snippet": r["snippet"],
                "mine": r["_values"]["mine"], "recommendation": (r["facets"] or {}).get("recommendation"),
                "vote": votes.get(r["doc_id"], 0)} for r in shown[:SHOWN]]
    return {"q": q, "norm": norm, "query_id": query_id, "total": len(shown), "capped": len(rows) >= CANDIDATES,
            "results": results, "facets": facets, "typo_tolerance": typo, "ai": embedder is not None}
