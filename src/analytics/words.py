"""Chances in words, the same everywhere in Sift (pages, AI tools, help).

People read "about 4 in 10" more accurately than "38%", so pages lead with
the frequency and a fixed word; exact percentages stay in the details."""

from __future__ import annotations

# (lowest number in 10, word), checked from the top
SCALE = ((8, "Very likely"), (6, "Likely"), (5, "About even"), (3, "Possible"), (1, "Unlikely"), (0, "Very unlikely"))


def in_ten(probability: float) -> int:
    return max(0, min(10, round(probability * 10)))


def chance_words(probability: float | None) -> dict | None:
    """{"in_ten": 4, "word": "Possible", "text": "about 4 in 10"}."""
    if probability is None:
        return None
    n = in_ten(probability)
    word = next(w for low, w in SCALE if n >= low)
    text = "less than 1 in 10" if n == 0 else "more than 9 in 10" if n == 10 else f"about {n} in 10"
    return {"in_ten": n, "word": word, "text": text}


def luck_odds(p_value: float | None) -> str | None:
    """A p-value as plain odds: "about a 1 in 40 chance"."""
    if p_value is None:
        return None
    if p_value < 0.001:
        return "less than a 1 in 1,000 chance"
    if p_value > 0.5:
        return "better than an even chance"
    return f"about a 1 in {round(1 / p_value):,} chance"
