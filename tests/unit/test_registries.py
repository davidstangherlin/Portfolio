"""Share registries (src/registries.py): recognising a registry however it's
written, and reading it from ASX's company details in either shape."""

import json

import pytest

from src import registries as r


@pytest.mark.parametrize("name, registry_id", [
    ("Computershare Investor Services Pty Limited", "computershare"),
    ("Link Market Services Limited", "mufg"),
    ("MUFG Corporate Markets (AU) Limited", "mufg"),
    ("Automic Pty Ltd", "automic"),
    ("Boardroom Pty Limited", "boardroom"),
    ("Advanced Share Registry Services", "advanced"),
    ("Xcend Pty Ltd", "xcend"),
])
def test_known_registries(name, registry_id):
    assert r.match(name).registry_id == registry_id


def test_unknown_names_and_ordinary_words():
    assert r.match("Smith Registry Services") is None
    assert r.match("links to the annual report") is None  # "link" alone isn't MUFG
    assert r.describe(None, "Smith Registry Services") == {"registry_id": None, "name": "Smith Registry Services", "portal": None, "website": None}
    assert r.describe("computershare", None)["portal"].startswith("https://")
    assert r.describe(None, None) is None


def test_reading_asx_company_details():
    nested = json.dumps({"data": {"description": "Miner", "shareRegistry": {"name": "Computershare Investor Services Pty Limited",
                                                                           "phone": "1300 000 000"}}}).encode()
    flat = json.dumps({"code": "GOOD", "registry_name": "Link Market Services Limited"}).encode()
    loose = json.dumps({"data": {"contacts": ["Automic Pty Ltd, Level 5, Sydney"]}}).encode()
    assert r.read_registry(nested) == "Computershare Investor Services Pty Limited"
    assert r.read_registry(flat) == "Link Market Services Limited"
    assert r.read_registry(loose) == "Automic Group"  # no registry field: the known name mentioned
    assert r.read_registry(b'{"data": {"description": "Miner"}}') is None and r.read_registry(b"<html>") is None


def test_lookup_tries_each_source():
    calls = []

    def fake(url):
        calls.append(url)
        return (404, b"") if "markitdigital" in url else (200, b'{"share_registry": {"name": "Boardroom Pty Limited"}}')
    assert r.lookup("good", fake) == "Boardroom Pty Limited"
    assert "companies/good/about" in calls[0] and "company/GOOD" in calls[1]
