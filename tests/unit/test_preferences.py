"""The dashboard layout's shape check before it's stored."""

import pytest

from src.preferences import MAX_CARDS, PreferenceError, clean_layout


def test_a_layout_keeps_order_and_fills_defaults():
    out = clean_layout({"cards": [{"id": "movers", "wide": False}, {"id": "attention", "hidden": True},
                                  {"id": "movers", "hidden": True}]})
    assert out == {"cards": [{"id": "movers", "hidden": False, "wide": False},
                             {"id": "attention", "hidden": True, "wide": None}]}


@pytest.mark.parametrize("body", [
    None, {}, {"cards": "x"}, {"cards": [{"id": "Bad Id"}]}, {"cards": [{"id": "ok", "hidden": "yes"}]},
    {"cards": [{"id": "ok", "wide": 1}]}, {"cards": [{"id": f"c{i}"} for i in range(MAX_CARDS + 1)]},
])
def test_anything_else_is_refused(body):
    with pytest.raises(PreferenceError):
        clean_layout(body)
