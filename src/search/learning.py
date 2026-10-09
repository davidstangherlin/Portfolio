"""How search improves with use (docs/AS_BUILT.md §32).

- Every search is logged (`search_queries`), with the number of results:
  searches that found nothing show in Admin, Search insights, as things to
  fix (usually with a synonym).
- Clicks on results (`search_clicks`) and thumbs up or down
  (`search_feedback`) raise or lower a result for that search (the same
  words, in any order of case) next time: `boosts()`.
- Synonyms (`search_synonyms`) widen a search: searching one term also
  finds the others in its group: `variants()`.

Owners: rows carry the searcher's owner_id (src/accounts.py, §33). Boosts pool
everyone's clicks and votes on shared results, which is what makes them
useful; a user's own votes show on their results."""

from __future__ import annotations

import math

from sqlalchemy import text

LOG_DAYS = 365          # how long the search log is kept
BOOST_DAYS = 180        # clicks and votes older than this stop counting
CLICK_WEIGHT = 0.6      # per log(1 + clicks)
VOTE_WEIGHT = 1.5       # per net vote
MAX_BOOST = 3.0
MAX_VARIANTS = 6


def owner_key(owner_id) -> str:
    return str(owner_id) if owner_id else ""


def log_query(session, query: str, norm: str, results: int, owner_id=None) -> int:
    return session.execute(text("""
        INSERT INTO search_queries (owner_id, query, norm, results) VALUES (:o, :q, :n, :r) RETURNING query_id
    """), {"o": owner_id, "q": query[:300], "n": norm[:300], "r": results}).scalar()


def record_click(session, query_id: int, doc_id: str, position: int | None, owner_id=None) -> None:
    """A click on a result of one of this person's own searches."""
    if session.execute(text("SELECT 1 FROM search_queries WHERE query_id = :q AND owner_id IS NOT DISTINCT FROM :o"),
                       {"q": query_id, "o": owner_id}).first():
        session.execute(text("INSERT INTO search_clicks (query_id, doc_id, position) VALUES (:q, :d, :p)"),
                        {"q": query_id, "d": doc_id[:160], "p": position})


def record_vote(session, norm: str, doc_id: str, vote: int, owner_id=None) -> None:
    """+1 or -1 replaces any earlier vote on this result for this search; 0 withdraws it."""
    key = {"k": owner_key(owner_id), "n": norm[:300], "d": doc_id[:160]}
    if vote == 0:
        session.execute(text("DELETE FROM search_feedback WHERE owner_key = :k AND norm = :n AND doc_id = :d"), key)
        return
    session.execute(text("""
        INSERT INTO search_feedback (owner_key, norm, doc_id, vote) VALUES (:k, :n, :d, :v)
        ON CONFLICT (owner_key, norm, doc_id) DO UPDATE SET vote = EXCLUDED.vote, voted_at = CURRENT_TIMESTAMP
    """), key | {"v": 1 if vote > 0 else -1})


def boosts(session, norm: str) -> dict[str, float]:
    """Extra score per result for this search, from recent clicks and votes."""
    clicks = dict(session.execute(text(f"""
        SELECT c.doc_id, count(*) FROM search_clicks c JOIN search_queries q USING (query_id)
        WHERE q.norm = :n AND c.clicked_at > now() - interval '{BOOST_DAYS} days' GROUP BY c.doc_id
    """), {"n": norm}).all())
    votes = dict(session.execute(text(f"""
        SELECT doc_id, sum(vote) FROM search_feedback
        WHERE norm = :n AND voted_at > now() - interval '{BOOST_DAYS} days' GROUP BY doc_id
    """), {"n": norm}).all())
    out = {}
    for doc in set(clicks) | set(votes):
        b = CLICK_WEIGHT * math.log1p(clicks.get(doc, 0)) + VOTE_WEIGHT * int(votes.get(doc, 0))
        out[doc] = max(-MAX_BOOST, min(MAX_BOOST, b))
    return out


def my_votes(session, norm: str, owner_id=None) -> dict[str, int]:
    return dict(session.execute(text("SELECT doc_id, vote FROM search_feedback WHERE owner_key = :k AND norm = :n"),
                                {"k": owner_key(owner_id), "n": norm}).all())


# ---------- synonyms ----------
def clean_terms(terms) -> list[str]:
    """Lower case, single spaces, letters, digits and spaces only, no repeats."""
    import re
    out = []
    for t in terms or []:
        t = " ".join(re.findall(r"[a-z0-9]+", str(t).lower()))
        if t and t not in out:
            out.append(t)
    return out


def list_synonyms(session) -> list[dict]:
    return [{"synonym_id": i, "terms": list(t)} for i, t in session.execute(
        text("SELECT synonym_id, terms FROM search_synonyms ORDER BY terms[1]"))]


def add_synonyms(session, terms) -> dict:
    terms = clean_terms(terms)
    if len(terms) < 2:
        raise ValueError("a synonym group needs two or more different terms")
    sid = session.execute(text("INSERT INTO search_synonyms (terms) VALUES (:t) RETURNING synonym_id"), {"t": terms}).scalar()
    return {"synonym_id": sid, "terms": terms}


def delete_synonyms(session, synonym_id: int) -> bool:
    return session.execute(text("DELETE FROM search_synonyms WHERE synonym_id = :i"), {"i": synonym_id}).rowcount > 0


def variants(session, ws: list[str]) -> list[list[str]]:
    """The query's words, then the same words with each synonym swapped in
    ("cba results" also searches "commonwealth bank results")."""
    out = [ws]
    for (terms,) in session.execute(text("SELECT terms FROM search_synonyms")):
        groups = [t.split() for t in terms]
        for term in groups:
            n = len(term)
            for i in range(len(ws) - n + 1):
                if ws[i:i + n] == term:
                    for other in groups:
                        if other != term:
                            v = ws[:i] + other + ws[i + n:]
                            if v not in out:
                                out.append(v)
    return out[:MAX_VARIANTS]


# ---------- insights for Admin ----------
def insights(session, days: int = 30) -> dict:
    window = {"d": days}
    top = [dict(r) for r in session.execute(text("""
        SELECT q.norm, count(*) AS searches, round(avg(q.results)) AS results,
               count(DISTINCT c.query_id) AS clicked
        FROM search_queries q LEFT JOIN search_clicks c USING (query_id)
        WHERE q.searched_at > now() - make_interval(days => :d)
        GROUP BY q.norm ORDER BY searches DESC, q.norm LIMIT 25
    """), window).mappings()]
    nothing = [dict(r) for r in session.execute(text("""
        SELECT norm, count(*) AS searches, max(searched_at) AS last FROM search_queries
        WHERE results = 0 AND searched_at > now() - make_interval(days => :d)
        GROUP BY norm ORDER BY searches DESC, last DESC LIMIT 25
    """), window).mappings()]
    disliked = [dict(r) for r in session.execute(text("""
        SELECT f.norm, f.doc_id, s.title, sum(f.vote) AS net, count(*) AS votes
        FROM search_feedback f LEFT JOIN search_index s USING (doc_id)
        GROUP BY f.norm, f.doc_id, s.title HAVING sum(f.vote) < 0 ORDER BY net, votes DESC LIMIT 25
    """)).mappings()]
    totals = session.execute(text("""
        SELECT count(*) AS searches, count(*) FILTER (WHERE results = 0) AS nothing,
               (SELECT count(*) FROM search_clicks c JOIN search_queries q USING (query_id)
                 WHERE q.searched_at > now() - make_interval(days => :d)) AS clicks
        FROM search_queries WHERE searched_at > now() - make_interval(days => :d)
    """), window).mappings().first()
    return {"days": days, "totals": dict(totals), "top": top, "nothing": nothing, "disliked": disliked}


def prune(session) -> int:
    """Drop log rows older than LOG_DAYS (their clicks go with them)."""
    return session.execute(text(f"DELETE FROM search_queries WHERE searched_at < now() - interval '{LOG_DAYS} days'")).rowcount
