"""Meaning-based search, ready and switched off (docs/AS_BUILT.md §32).

An embedding is a row's meaning as a list of numbers: rows about similar
things have similar numbers, so "companies hurt by high interest rates"
can find a bank or a REIT without those words. When an embedder is on:

- each index row's text is embedded once and kept until the text changes
  (search_index.content_hash), so a nightly rebuild only embeds new or
  changed rows;
- each search embeds the query once and blends meaning matches with word
  matches (reciprocal rank fusion, in src/search/query.py).

Switch on (a small model that runs inside Sift; nothing leaves the PC or
server): pip install sentence-transformers, add SIFT_EMBEDDINGS=local to
.env (SIFT_EMBEDDING_MODEL to choose another model), restart Sift, then
rebuild the search index (Admin, Search). Off, search works as before.

Scale: rows are compared in memory with numpy, which is quick to tens of
thousands of rows. On a host with pgvector (Supabase has it), the
embedding column can become vector(n) with an HNSW index and the
comparison move into SQL; nothing else changes."""

from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384 numbers per row, about 90MB, fast on a CPU
MIN_SIMILARITY = 0.30   # weaker meaning matches are left out
SEMANTIC_LIMIT = 50
BATCH = 64

_override = None  # tests set an embedder here


def content_hash(title: str, subtitle: str | None, body: str | None) -> str:
    return hashlib.sha1(f"{title}\x1f{subtitle or ''}\x1f{body or ''}".encode("utf-8")).hexdigest()


def doc_text(title: str, subtitle: str | None, body: str | None) -> str:
    """What's embedded for a row: its title, subtitle and the start of its body."""
    return ". ".join(x for x in (title, subtitle, (body or "")[:1500]) if x)


class LocalEmbedder:
    """A sentence-transformers model running in Sift's own process."""

    def __init__(self, model: str):
        self.name = model
        self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.name)
        return self._model.encode(texts, batch_size=BATCH, normalize_embeddings=True).tolist()


@lru_cache(maxsize=1)
def _configured():
    mode = os.getenv("SIFT_EMBEDDINGS", "").strip().lower()
    if mode in ("", "off", "none"):
        return None
    if mode == "local":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            logger.warning("SIFT_EMBEDDINGS=local but sentence-transformers isn't installed: meaning-based search stays off")
            return None
        return LocalEmbedder(os.getenv("SIFT_EMBEDDING_MODEL", DEFAULT_MODEL))
    logger.warning("SIFT_EMBEDDINGS=%s isn't a known embedder (use local or off): meaning-based search stays off", mode)
    return None


def get_embedder():
    """The embedder in use, or None (the default: off)."""
    return _override if _override is not None else _configured()


def embed_missing(session, embedder, areas=None) -> int:
    """Embed rows with no embedding, or one from another model. Returns how many."""
    where = "(embedding IS NULL OR embedding_model IS DISTINCT FROM :m)"
    params = {"m": embedder.name}
    if areas:
        where += " AND area = ANY(:a)"
        params["a"] = list(areas)
    rows = session.execute(text(f"SELECT doc_id, title, subtitle, body FROM search_index WHERE {where}"), params).all()
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        vectors = embedder.embed([doc_text(t, s, b) for _, t, s, b in chunk])
        session.execute(text("UPDATE search_index SET embedding = :e, embedding_model = :m WHERE doc_id = :d"),
                        [{"e": v, "m": embedder.name, "d": d} for (d, *_), v in zip(chunk, vectors)])
    if rows:
        _matrix.cache_clear()
    return len(rows)


@lru_cache(maxsize=1)
def _matrix(version: str, model: str):
    """Every embedded row as one numpy matrix, rebuilt when the index changes."""
    import numpy as np

    from src.config import get_session
    with get_session() as session:
        rows = session.execute(text("SELECT doc_id, owner_id, embedding FROM search_index WHERE embedding_model = :m"),
                               {"m": model}).all()
    if not rows:
        return [], [], None
    return [r[0] for r in rows], [r[1] for r in rows], np.asarray([r[2] for r in rows], dtype="float32")


def semantic_matches(session, embedder, query: str, owner_id=None) -> list[tuple[str, float]]:
    """(doc_id, similarity) for the rows closest in meaning to the query, best first."""
    import numpy as np

    version = str(session.execute(text("SELECT coalesce(max(run_id), 0) FROM search_index_runs")).scalar())
    ids, owners, matrix = _matrix(version, embedder.name)
    if matrix is None:
        return []
    sims = matrix @ np.asarray(embedder.embed([query])[0], dtype="float32")
    order = np.argsort(-sims)[:SEMANTIC_LIMIT * 2]
    return [(ids[i], float(sims[i])) for i in order
            if sims[i] >= MIN_SIMILARITY and (owners[i] is None or owners[i] == owner_id)][:SEMANTIC_LIMIT]


def status(session) -> dict:
    e = get_embedder()
    counts = session.execute(text("""
        SELECT count(*) AS rows, count(embedding) AS embedded FROM search_index""")).mappings().first()
    return {"on": e is not None, "model": e.name if e else None, "rows": counts["rows"], "embedded": counts["embedded"],
            "how": "pip install sentence-transformers, add SIFT_EMBEDDINGS=local to .env, restart Sift, then rebuild the index"}
