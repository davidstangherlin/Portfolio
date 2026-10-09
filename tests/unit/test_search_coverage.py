"""Search keeps up as Sift grows (docs/AS_BUILT.md §32): every table is either
searched or excluded with a reason, and every page in the menu bar is in
the index. A new table or page fails here until it's classified."""

import re
from pathlib import Path

from src.search.indexer import AREAS, EXCLUDED, PAGES, SOURCES

ROOT = Path(__file__).resolve().parents[2]


def test_every_table_is_searched_or_excluded_with_a_reason():
    tables = set(re.findall(r"^CREATE TABLE IF NOT EXISTS (\w+)", (ROOT / "db" / "schema.sql").read_text(encoding="utf-8"), re.M))
    unclassified = tables - set(SOURCES) - set(EXCLUDED)
    assert not unclassified, (f"New table(s) {sorted(unclassified)}: add each to SOURCES in src/search/indexer.py "
                              "(and index it in that area's builder) or to EXCLUDED with the reason it isn't searched.")
    assert not set(SOURCES) & set(EXCLUDED)
    assert not (set(SOURCES) | set(EXCLUDED)) - tables, "SOURCES or EXCLUDED names a table that no longer exists"
    assert set(SOURCES.values()) <= set(AREAS)
    assert all(reason.strip() for reason in EXCLUDED.values())


def test_every_menu_page_is_in_the_index():
    links = set(re.findall(r'<a href="(#/[a-z-]*)"', (ROOT / "web" / "index.html").read_text(encoding="utf-8")))
    links = {l for l in links if "?" not in l}
    indexed = {url for _, url, _ in PAGES}
    assert not links - indexed, f"Menu page(s) {sorted(links - indexed)} missing from PAGES in src/search/indexer.py"
