"""The developer knowledge base (docs/AS_BUILT.md §36): every article's
header is complete and valid, every link and code path points somewhere
real, the register is well formed, release notes match the version, house
style holds, and the Markdown renderer escapes everything it's given."""

import re
from datetime import date

import pytest

from src import version
from src.devkb import articles, generated, markdown, register

ARTICLES = articles.load()
IDS = {a.id for a in ARTICLES} | set(generated.GENERATED)


def test_articles_load_and_ids_match_file_names():
    assert len(ARTICLES) >= 50
    assert len({a.id for a in ARTICLES}) == len(ARTICLES)
    for a in ARTICLES:
        assert a.path.endswith(f"/{a.id}.md"), a.path
        assert re.fullmatch(r"[a-z0-9-]+", a.id)


def test_every_category_has_articles_and_the_folder_matches():
    folders = {a.category: a.path.split("/")[2] for a in ARTICLES}
    assert set(folders) >= set(articles.CATEGORIES) - {"reference"}
    assert all(folder == cat for cat, folder in folders.items())


@pytest.mark.parametrize("article", ARTICLES, ids=[a.id for a in ARTICLES])
def test_article_is_complete_and_sound(article):
    assert article.summary.endswith(".") and len(article.summary) < 260
    assert article.published <= article.reviewed < article.next_review
    for r in article.related:
        assert r in IDS, f"related {r!r} isn't an article"
    for path in article.code:
        assert (articles.ROOT / path.rstrip("/")).exists() or path == "allords.txt", f"no file {path}"
    for target in re.findall(r"\]\(kb:([a-z0-9-]+)", re.sub(r"`[^`]*`", "", article.body)):  # examples in code don't count
        assert target in IDS, f"link to unknown article {target!r}"
    assert "—" not in article.body + article.title + article.summary, "no em dashes (house style)"
    if article.category == "decisions" and article.id.startswith("adr-"):
        assert article.decision_status in ("proposed", "accepted", "superseded", "deprecated")
        for heading in ("## Status", "## Context", "## Decision", "## Options considered", "## Consequences", "## Revisit when"):
            assert heading in article.body
    if article.category == "features":
        for heading in ("## Purpose", "## How it works", "## Code map", "## Diagnosing problems", "## Known limits", "## Tests"):
            assert heading in article.body
    if article.id.startswith("rb-"):
        for heading in ("## Verify", "## Prevent and escalate"):
            assert heading in article.body


def test_tables_named_in_articles_exist_in_the_schema():
    schema = (articles.ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema))
    for a in ARTICLES:
        for t in a.tables:
            assert t in tables, (a.id, t)


def test_release_notes_match_the_version():
    notes = [a for a in ARTICLES if a.category == "releases"]
    assert notes and all(a.release for a in notes)
    assert len({a.release for a in notes}) == len(notes)
    assert all(a.id == "release-" + a.release.replace(".", "-") for a in notes)
    newest = max(notes, key=lambda a: tuple(int(x) for x in a.release.split(".")))
    assert newest.release == version.VERSION
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", version.VERSION)
    assert date.fromisoformat(version.RELEASED) == newest.published


def test_register_is_well_formed():
    items = register.load()
    register.check(items, IDS)
    assert [i["id"] for i in items][:36] == [f"IMP-{n:03d}" for n in range(1, 37)]  # AS_BUILT's known issue numbers


def test_a_bad_header_is_refused():
    good = "---\nid: x\ntitle: X\ncategory: features\nsummary: S.\nversion: 1.0\nstatus: published\nowner: O\npublished: 2026-10-09\nreviewed: 2026-10-09\nnext_review: 2027-01-09\n---\nBody\n"
    assert articles.parse(good, "docs/kb/features/x.md").title == "X"
    for broken, why in ((good.replace("version: 1.0", "version: one"), "version"),
                        (good.replace("next_review: 2027-01-09", "next_review: 2026-01-09"), "after reviewed"),
                        (good.replace("category: features", "category: misc"), "category"),
                        (good.replace("owner: O\n", ""), "missing owner"),
                        (good.replace("owner: O", "owner: O\ncolour: red"), "unknown header")):
        with pytest.raises(articles.ArticleError, match=why):
            articles.parse(broken, "docs/kb/features/x.md")


def test_review_states():
    a = articles.parse("---\nid: x\ntitle: X\ncategory: features\nsummary: S.\nversion: 1.0\nstatus: published\nowner: O\n"
                       "published: 2026-01-01\nreviewed: 2026-01-01\nnext_review: 2026-11-01\n---\n", "x.md")
    assert a.review_state(date(2026, 9, 1)) == "ok"
    assert a.review_state(date(2026, 10, 15)) == "due"
    assert a.review_state(date(2026, 11, 2)) == "overdue"


def test_markdown_escapes_and_renders():
    html, toc = markdown.render(
        "# Title <b>\n\nText with <script>x</script>, **bold**, *it*, `<code>` and ~~old~~.\n\n"
        "- one\n  - nested\n- two\n\n1. first\n2. second\n\n| A | B |\n|---|---|\n| <i>1</i> | 2 |\n\n"
        "```\n<raw> & stuff\n```\n\n> quoted\n\n---\n\n"
        "[ok](kb:search) [page](#/screener) [web](https://example.com) [bad](javascript:alert(1)) IMP-004\n")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert '<h2 id="title">Title &lt;b&gt;</h2>' in html and toc[0] == {"level": 2, "id": "title", "text": "Title &lt;b&gt;"}
    assert "<strong>bold</strong>" in html and "<em>it</em>" in html and "<code>&lt;code&gt;</code>" in html and "<del>old</del>" in html
    assert "<ul><li>one<ul><li>nested</li></ul></li><li>two</li></ul>" in html and "<ol><li>first</li><li>second</li></ol>" in html
    assert "<td>&lt;i&gt;1&lt;/i&gt;</td>" in html and "<pre><code>&lt;raw&gt; &amp; stuff</code></pre>" in html
    assert "<blockquote>" in html and "<hr>" in html
    assert 'href="#/admin/kb/search"' in html and 'href="#/screener"' in html
    assert 'href="https://example.com" target="_blank" rel="noopener noreferrer"' in html
    assert 'href="javascript' not in html and ">bad<" not in html  # the unsafe link stays plain text
    assert 'href="#/admin/kb/register?q=IMP-004"' in html


def test_plain_text_for_search():
    assert markdown.plain("## Head\n\n**Bold** [link](kb:x) `code`\n```\nskip\n```") == "Head Bold link code"


def test_generated_pages_that_need_no_database():
    assert "| `rows_shown` |" in generated.settings_reference() and "discount_rate" in generated.settings_reference()
    cat = generated.test_catalogue()
    assert "tests/unit/test_devkb.py" in cat and "test functions" in cat
