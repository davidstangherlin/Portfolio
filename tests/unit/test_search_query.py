"""Search query words (docs/AS_BUILT.md §32)."""

from src.search.query import tsquery_sql, words


def test_words_are_safe_lower_case_and_skip_little_words():
    assert words("Margin of SAFETY!") == ["margin", "safety"]
    assert words("BHP; DROP TABLE x--") == ["bhp", "drop", "table", "x"]  # letters and digits only: safe in a tsquery
    assert words("the") == ["the"]  # a query of only little words keeps them
    assert words("   ") == []


def test_each_word_matches_stemmed_or_as_a_word_start():
    assert tsquery_sql(2) == ("(to_tsquery('english', :w0) || to_tsquery('simple', :p0)) && "
                              "(to_tsquery('english', :w1) || to_tsquery('simple', :p1))")
