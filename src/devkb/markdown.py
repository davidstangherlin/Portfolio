"""A small, safe Markdown renderer for the developer knowledge base (§36).

Covers what the articles use: headings, paragraphs, bold, italics, strike,
inline code, fenced code, lists (nested by indentation), tables, quotes,
rules and links. Every piece of text is HTML-escaped before markup is added,
so an article can't inject script or markup into the page. Links may go to
Sift pages (#/...), other articles (kb:article-id) or the web (https://...);
anything else is shown as plain text. IMP-001 style references link to the
improvement register."""

from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_FENCE = re.compile(r"^\s*```")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")


def slug(text: str) -> str:
    """A heading's anchor: lower case letters, digits and hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>|&\w+;", "", text).lower()).strip("-") or "section"


def _href(target: str) -> tuple[str, bool] | None:
    """(url, external) for a link target Sift allows, or None."""
    target = target.strip()
    if target.startswith("kb:"):
        rest = target[3:]
        article, _, anchor = rest.partition("#")
        if re.fullmatch(r"[a-z0-9-]+", article):
            return f"#/admin/kb/{article}" + (f"?section={anchor}" if anchor else ""), False
        return None
    if target.startswith("#/"):
        return target, False
    if re.match(r"https?://", target):
        return target, True
    return None


def inline(text: str) -> str:
    """Escape, then add inline markup. Code spans are protected first."""
    codes: list[str] = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1), quote=False)}</code>")
        return f"\u0000{len(codes) - 1}\u0000"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)

    def link(m):
        label, target = m.group(1), html.unescape(m.group(2))
        found = _href(target)
        if found is None:
            return label
        url, external = found
        extra = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return f'<a href="{html.escape(url)}"{extra}>{label}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
    # Register items (IMP-004) open the improvement register searched for them.
    text = re.sub(r"(?<![\w-])IMP-(\d{3})(?![\w-])", r'<a href="#/admin/kb/register?q=IMP-\1">IMP-\1</a>', text)
    return re.sub("\u0000(\\d+)\u0000", lambda m: codes[int(m.group(1))], text)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _list(lines: list[str], i: int) -> tuple[str, int]:
    """A list starting at lines[i] (and any lists nested in it). Returns (html, next index)."""
    first = _LIST.match(lines[i])
    indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    items: list[list[str]] = []  # each item: its text, then rendered child blocks
    while i < len(lines):
        line = lines[i]
        m = _LIST.match(line)
        if m and len(m.group(1)) == indent:
            items.append([inline(m.group(3))])
            i += 1
        elif m and len(m.group(1)) > indent and items:
            child, i = _list(lines, i)
            items[-1].append(child)
        elif line.strip() and items and not m and (len(line) - len(line.lstrip())) > indent:
            items[-1][0] += " " + inline(line.strip())  # a wrapped line of the same item
            i += 1
        else:
            break
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{''.join(parts)}</li>" for parts in items) + f"</{tag}>", i


def render(text: str) -> tuple[str, list[dict]]:
    """(HTML, table of contents [{level, id, text}]) for a Markdown article body."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    toc: list[dict] = []
    used: dict[str, int] = {}
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(p.strip() for p in para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if _FENCE.match(line):
            flush()
            lang = line.strip()[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            cls = f' class="lang-{html.escape(lang)}"' if re.fullmatch(r"[a-z0-9-]+", lang or "x") and lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(body), quote=False)}</code></pre>")
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            level = max(2, len(m.group(1)))  # the page's h1 is the article title, so "#" and "##" are both h2
            content = inline(m.group(2))
            anchor = slug(m.group(2))
            used[anchor] = used.get(anchor, 0) + 1
            if used[anchor] > 1:
                anchor = f"{anchor}-{used[anchor]}"
            toc.append({"level": level, "id": anchor, "text": re.sub(r"<[^>]+>", "", content)})
            out.append(f'<h{min(level, 5)} id="{anchor}">{content}</h{min(level, 5)}>')
            i += 1
            continue
        if _RULE.match(line):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            out.append('<div class="table-wrap"><table class="grid kb-table"><thead><tr>'
                       + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table></div>")
            continue
        if _LIST.match(line):
            flush()
            block, i = _list(lines, i)
            out.append(block)
            continue
        if line.lstrip().startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out), toc


def plain(text: str) -> str:
    """The words of an article without markup, for search."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*`>|~_]+", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"-{3,}", " ", text)).strip()
