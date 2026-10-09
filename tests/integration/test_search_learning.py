"""Search improves with use, and is ready for meaning-based search
(docs/AS_BUILT.md §32): clicks and thumbs move results, synonyms widen a
search, failed searches show in insights, and with an embedder switched on
rows are embedded once and meaning matches are blended in."""

import math
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import gui
from src.search import embeddings, indexer, learning
from src.search.query import search
from tests.integration.test_screener import _seed_and_value

pytestmark = pytest.mark.integration
WRITE = {"X-Sift": "1"}


@pytest.fixture()
def indexed(db_session):
    _seed_and_value(db_session, "GOOD", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("10.00"))
    _seed_and_value(db_session, "DEAR", "Basic Materials", Decimal("110000000"), Decimal("0.60"), Decimal("60.00"))
    indexer.reindex(db_session, today=date(2026, 10, 5))
    db_session.commit()
    return db_session


def _order(session, q):
    return [x["code"] for x in search(session, q)["results"] if x["code"]]


def test_clicks_and_thumbs_move_a_result_up(indexed):
    before = _order(indexed, "basic materials")
    last = before[-1]
    client = TestClient(gui.create_app())
    first = client.get("/api/search", params={"q": "Basic Materials", "log": "1"}).json()
    doc = next(x["doc_id"] for x in first["results"] if x["code"] == last)
    assert client.post("/api/search/click", json={"query_id": first["query_id"], "doc_id": doc, "position": 2}, headers=WRITE).json()["ok"]
    client.post("/api/search/feedback", json={"norm": first["norm"], "doc_id": doc, "vote": 1}, headers=WRITE)
    after = client.get("/api/search", params={"q": "basic materials"}).json()
    assert after["results"][0]["code"] == last and after["results"][0]["vote"] == 1
    assert learning.boosts(indexed, "basic materials")[doc] == pytest.approx(learning.CLICK_WEIGHT * math.log1p(1) + learning.VOTE_WEIGHT)
    client.post("/api/search/feedback", json={"norm": first["norm"], "doc_id": doc, "vote": 0}, headers=WRITE)  # withdrawn
    assert indexed.execute(text("SELECT count(*) FROM search_feedback")).scalar() == 0
    assert client.post("/api/search/feedback", json={"norm": "x", "doc_id": doc, "vote": 5}, headers=WRITE).status_code == 400


def test_synonyms_widen_a_search(indexed):
    assert search(indexed, "pebbles")["total"] == 0
    client = TestClient(gui.create_app())
    added = client.post("/api/admin/search/synonyms", json={"terms": "Pebbles, basic materials"}, headers=WRITE).json()
    assert added["added"]["terms"] == ["pebbles", "basic materials"]
    assert {x["code"] for x in search(indexed, "pebbles")["results"] if x["code"]} == {"GOOD", "DEAR"}
    assert client.post("/api/admin/search/synonyms", json={"terms": "solo"}, headers=WRITE).status_code == 400
    client.delete(f"/api/admin/search/synonyms/{added['added']['synonym_id']}", headers=WRITE)
    assert search(indexed, "pebbles")["total"] == 0


def test_insights_list_top_and_failed_searches(indexed):
    client = TestClient(gui.create_app())
    for q in ("good", "good", "nonexistentthing"):
        client.get("/api/search", params={"q": q, "log": "1"})
    client.get("/api/search", params={"q": "good", "type": "Shares"})  # a tick box: not logged again
    ins = client.get("/api/admin/search/insights").json()
    assert ins["totals"]["searches"] == 3 and ins["totals"]["nothing"] == 1
    assert ins["top"][0]["norm"] == "good" and ins["top"][0]["searches"] == 2
    assert [x["norm"] for x in ins["nothing"]] == ["nonexistentthing"]


class FakeEmbedder:
    """Stands in for the real model: words about lending and banks share a
    direction, so meaning can match without the word."""
    name = "fake-test-model"
    CONCEPTS = {"lending": 0, "bank": 0, "banks": 0, "loans": 0, "mining": 1, "materials": 1, "rocks": 1}

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += len(texts)
        out = []
        for t in texts:
            v = [0.0] * 8
            for w in t.lower().replace(".", " ").split():
                v[self.CONCEPTS.get(w, 2 + hash(w) % 6)] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


@pytest.fixture()
def fake_embedder():
    e = FakeEmbedder()
    embeddings._override = e
    embeddings._matrix.cache_clear()
    yield e
    embeddings._override = None
    embeddings._matrix.cache_clear()


def test_ai_ready_rows_are_embedded_once_and_meaning_matches_are_blended(indexed, fake_embedder):
    indexed.execute(text("INSERT INTO scenarios (name, notes, owner_id) SELECT 'Bank squeeze', 'Bank loans', user_id FROM users"))
    indexer.reindex(indexed, today=date(2026, 10, 5))
    indexed.commit()
    rows = indexed.execute(text("SELECT count(*) FROM search_index")).scalar()
    assert fake_embedder.calls == rows  # every row embedded once
    indexer.reindex(indexed, today=date(2026, 10, 5))
    indexed.commit()
    assert fake_embedder.calls == rows  # nothing changed: nothing embedded again
    meaning_only = search(indexed, "lending")  # no row has the word: found by meaning alone
    assert meaning_only["ai"] is True and meaning_only["results"][0]["title"] == "Bank squeeze"
    before = fake_embedder.calls  # the search above embedded its query
    indexed.execute(text("UPDATE scenarios SET notes = 'Bank loans and lending'"))
    indexer.reindex(indexed, ("personal",))
    indexed.commit()
    assert fake_embedder.calls == before + 1  # only the changed row
    assert search(indexed, "lending")["results"][0]["title"] == "Bank squeeze"  # now by word and meaning
    status = TestClient(gui.create_app()).get("/api/admin/search").json()["ai"]
    assert status["on"] and status["embedded"] == status["rows"] and status["model"] == "fake-test-model"


def test_ai_is_off_by_default(indexed):
    assert embeddings.get_embedder() is None
    assert indexed.execute(text("SELECT count(embedding) FROM search_index")).scalar() == 0
    assert search(indexed, "good")["ai"] is False
