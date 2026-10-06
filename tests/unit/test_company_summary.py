"""The company page's short description (docs/AS_BUILT.md §28)."""

from gui import short_summary

INFRATIL = ("Infratil Limited owns and invests in infrastructure businesses in New Zealand, Australia, the U.S. "
            "and Europe. It operates through CDC Data Centres, One NZ, Manawa Energy and other segments. The company "
            "was founded in 1994 and is headquartered in Wellington, New Zealand.")


def test_first_two_sentences():
    assert short_summary(INFRATIL) == (
        "Infratil Limited owns and invests in infrastructure businesses in New Zealand, Australia, the U.S. "
        "and Europe. It operates through CDC Data Centres, One NZ, Manawa Energy and other segments.")


def test_abbreviations_do_not_end_a_sentence():
    text = "Acme Pty. Ltd. sells rope. It has 3 mines, e.g. Mt. Isa. It was founded in 1901."
    assert short_summary(text) == "Acme Pty. Ltd. sells rope. It has 3 mines, e.g. Mt. Isa."


def test_short_or_missing_summaries():
    assert short_summary("Holds cash.") == "Holds cash."
    assert short_summary("One. Two.") == "One. Two."
    assert short_summary("") is None and short_summary(None) is None
