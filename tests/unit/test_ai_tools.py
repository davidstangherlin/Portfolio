"""The AI tool catalogue (src/ai/tools.py): every tool is described with a
JSON Schema an assistant can use, and answers come out as plain JSON."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from src.ai import tools


def test_every_tool_is_described_with_a_schema():
    names = [t["name"] for t in tools.catalogue()]
    assert len(names) == len(set(names)) >= 10
    for t in tools.catalogue():
        assert t["description"].endswith(".") and len(t["description"]) > 40
        schema = t["input_schema"]
        assert schema["type"] == "object" and set(schema["required"]) <= set(schema["properties"])
        for spec in schema["properties"].values():
            assert spec["type"] in ("string", "integer", "boolean", "array") and spec["description"]


def test_answers_are_plain_json():
    out = tools.jsonable({"a": Decimal("1.50"), "d": date(2026, 10, 9), "u": UUID(int=1), "l": (Decimal("2"),)})
    assert out == {"a": 1.5, "d": "2026-10-09", "u": "00000000-0000-0000-0000-000000000001", "l": [2.0]}
