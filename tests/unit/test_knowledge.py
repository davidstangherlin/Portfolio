"""web/knowledge.json: the single source for Sift's Help page, its hover
explanations and the Word glossary. These checks stop a hand edit from
breaking any of the three."""

import json
import re
from pathlib import Path

import pytest

KB = json.loads((Path(__file__).resolve().parents[2] / "web" / "knowledge.json").read_text(encoding="utf-8"))
ENTRIES = KB["entries"]
IDS = [e["id"] for e in ENTRIES]
PLACEHOLDERS = {"margin_of_safety", "roe", "debt_to_equity", "yield"}

# Every label Sift explains on hover (web/app.js asks for these by name).
UI_LABELS = [
    "Score", "Company", "Sector", "Price", "Margin of safety", "ROE", "Debt/equity", "Yield (grossed up)",
    "Grossed-up yield", "Value tests", "Action", "Earnings quality", "Price signal", "Dividend trend",
    "Fundamentals trend", "Margin of safety trend", "Value-trap risk", "Data confidence", "P/E", "P/B",
    "Price to free cash flow", "EV/EBIT", "ROIC", "Cash dividend yield", "Payout ratio", "Country",
    "Accounts currency", "Valuation", "Implied upside", "Estimated value", "Share price", "Portfolio value",
    "Today", "Unrealised gain", "Cost base", "CGT discount from", "Graham Number",
    # ETFs (§26)
    "ETF", "Fee", "Fund size", "Spread", "Net flows", "1-year return", "3-year return", "5-year return",
    "10-year return", "Yield (12 months)", "Unit price", "Day move", "Category", "Issuer", "Category average",
    "Reference fund", "ASX report", "Category median", "Rank in category", "Against its index",
    # LICs (§27)
    "LIC", "NTA (pre-tax)", "Premium/discount to NTA", "Performance fee", "Market cap",
    # Analysts and holders (§29)
    "Major holders", "Insiders", "Institutions", "Institutions (% of float)",
    "Number of institutions", "Top mutual fund holders", "Top institutional holders",
]


def _texts(e):
    return [e.get("definition") or "", e.get("hover") or "", *e.get("body", [])]


def test_ids_are_unique_and_url_safe():
    assert len(IDS) == len(set(IDS))
    assert all(re.fullmatch(r"[a-z0-9-]+", i) for i in IDS)


def test_every_entry_is_complete_and_filed():
    categories = {c["id"] for c in KB["categories"]}
    for e in ENTRIES:
        assert e["title"] and e.get("definition"), e["id"]
        assert e["category"] in categories, e["id"]


def test_links_point_somewhere_real():
    for e in ENTRIES:
        for r in e.get("related", []):
            assert r in IDS, (e["id"], r)
        for link in e.get("links", []):
            assert link["href"].startswith("#/"), (e["id"], link)


def test_every_hover_label_is_explained_exactly_once():
    labels = [l for e in ENTRIES for l in e.get("labels", [])]
    assert len(labels) == len(set(labels))
    assert set(UI_LABELS) <= set(labels)
    assert all(e.get("hover") or e.get("definition") for e in ENTRIES if e.get("labels"))


def test_both_valuation_models_are_explained():
    by_id = {e["id"]: e for e in ENTRIES}
    assert "discounted cash flow" in by_id["dcf"]["hover"] and "dividend discount" in by_id["ddm"]["hover"]


def test_glossary_entries_have_what_the_word_document_needs():
    acronyms = [e for e in ENTRIES if e.get("glossary") == "acronym"]
    terms = [e for e in ENTRIES if e.get("glossary") == "term"]
    assert all(e.get("abbreviation") and e.get("full") for e in acronyms)
    assert all(e.get("glossary_title") for e in terms)
    assert len({e["abbreviation"] for e in acronyms}) == len(acronyms)
    assert len(acronyms) >= 23 and len(terms) >= 27  # nothing lost from the original glossary


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_text_rules(entry):
    for text in _texts(entry):
        assert "—" not in text, "no em dashes (house style)"
        assert set(re.findall(r"\{(\w+)\}", text)) <= PLACEHOLDERS, "unknown {placeholder}"
