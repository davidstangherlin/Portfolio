"""Reference pages built from Sift itself, so they can't go out of date (§36):
the data dictionary (from the database and db/schema.sql), the API
reference (from the app's routes), settings (model settings and personal
preferences), dependencies and the test catalogue. Each returns Markdown,
rendered like any article."""

from __future__ import annotations

import ast
import importlib.metadata
import re
from datetime import date

from sqlalchemy import text

from src.devkb.articles import ROOT

GENERATED = {
    "ref-data-dictionary": ("Data dictionary", "data", "Every table and column in the live database, with what each table is for, who owns its rows and roughly how many there are."),
    "ref-api": ("API reference", "reference", "Every route the server answers, who may call it and what it does."),
    "ref-settings": ("Settings reference", "reference", "Every model setting (live value, range, formula) and every personal preference (default and choices)."),
    "ref-dependencies": ("Dependencies and services", "reference", "Python packages (pinned and installed), the database version and the outside services Sift relies on."),
    "ref-tests": ("Test catalogue", "reference", "Every test file and what it proves, with the number of tests in each."),
}


def _md_cell(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _schema_notes() -> dict[str, dict[str, str]]:
    """{table: {column: the comment written beside it in db/schema.sql}}."""
    notes: dict[str, dict[str, str]] = {}
    table = None
    for line in (ROOT / "db" / "schema.sql").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*CREATE TABLE IF NOT EXISTS (\w+)", line)
        if m:
            table = m.group(1)
            notes.setdefault(table, {})
            continue
        if table and line.strip().startswith(")"):
            table = None
            continue
        m = re.match(r"\s+(\w+)\s+[A-Z].*?--\s*(.+)$", line)
        if table and m:
            notes[table][m.group(1)] = m.group(2).strip()
        m = re.match(r"\s*ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+) .*?--\s*(.+)$", line)
        if m:
            notes.setdefault(m.group(1), {})[m.group(2)] = m.group(3).strip()
    return notes


def data_dictionary(session) -> str:
    from src.search.indexer import EXCLUDED, SOURCES

    notes = _schema_notes()
    columns: dict[str, list] = {}
    for r in session.execute(text("""
            SELECT table_name, column_name, data_type, character_maximum_length, numeric_precision, numeric_scale,
                   is_nullable, column_default
            FROM information_schema.columns c
            WHERE table_schema = 'public' AND table_name IN (SELECT table_name FROM information_schema.tables
                                                             WHERE table_schema = 'public' AND table_type = 'BASE TABLE')
            ORDER BY table_name, ordinal_position""")).mappings():
        columns.setdefault(r["table_name"], []).append(r)
    rows = dict(session.execute(text("""
        SELECT relname, GREATEST(reltuples, 0)::bigint FROM pg_class
        WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace""")).all())
    views = [v for (v,) in session.execute(text("SELECT table_name FROM information_schema.views WHERE table_schema = 'public' ORDER BY 1"))]

    def kind(r) -> str:
        t = r["data_type"]
        if r["character_maximum_length"]:
            return f"{t}({r['character_maximum_length']})"
        if t == "numeric" and r["numeric_precision"]:
            return f"numeric({r['numeric_precision']},{r['numeric_scale']})"
        return t

    out = [f"Built from the live database on {date.today():%d %B %Y}; column notes come from `db/schema.sql`. "
           "Row counts are PostgreSQL's estimates (refreshed by autovacuum), good for scale, not exact.",
           "", f"**{len(columns)} tables**, {len(views)} view(s): {', '.join(f'`{v}`' for v in views) or 'none'}.", ""]
    out += ["| Table | Purpose | Owner | Rows (approx.) |", "|---|---|---|---|"]
    for t in sorted(columns):
        personal = any(c["column_name"] == "owner_id" for c in columns[t])
        purpose = (f"searched ({SOURCES[t]} area)" if t in SOURCES else EXCLUDED.get(t, ""))
        out.append(f"| [{t}](kb:ref-data-dictionary#{t}) | {_md_cell(purpose)} | {'per person' if personal else 'shared'} | {rows.get(t, 0):,} |")
    for t in sorted(columns):
        out += ["", f"## {t}", "", "| Column | Type | Null | Default | Notes |", "|---|---|---|---|---|"]
        for c in columns[t]:
            default = (c["column_default"] or "")[:40]
            out.append(f"| `{c['column_name']}` | {kind(c)} | {'yes' if c['is_nullable'] == 'YES' else 'no'} | "
                       f"{_md_cell(default)} | {_md_cell(notes.get(t, {}).get(c['column_name'], ''))} |")
    return "\n".join(out) + "\n"


def api_reference(app) -> str:
    out = ["Built from the server's routes. **Access:** *admin* routes (under `/api/admin/`) refuse members; every "
           "*change* (POST, PUT, PATCH, DELETE) must come from Sift's own pages (the `X-Sift` header); every `/api/` "
           "route needs a signed-in, active account and acts for that person, or for whom an admin is impersonating.",
           "", "| Method | Path | Access | What it does |", "|---|---|---|---|"]
    entries = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or not methods:
            continue
        doc = (getattr(route, "endpoint", None).__doc__ or "").strip().split("\n\n")[0]
        doc = " ".join(doc.split()) or getattr(route, "name", "").replace("_", " ")
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            access = "admin" if path.startswith("/api/admin/") else "signed in"
            if method != "GET":
                access += ", change"
            entries.append((path, method, access, doc))
    for path, method, access, doc in sorted(entries):
        out.append(f"| {method} | `{_md_cell(path)}` | {access} | {_md_cell(doc)} |")
    out += ["", f"**{len(entries)} routes.** Static files are served from `/static` and the page itself from `/`."]
    return "\n".join(out) + "\n"


def settings_reference() -> str:
    from src.preferences import SETTINGS_SPEC
    from src.settings import GROUPS, LIVE, SETTINGS, to_display

    groups = dict(GROUPS)
    out = ["## Model settings", "", "The live values behind valuations, the four tests, actions and the score wheel "
           "(`src/settings.py`). Changed only in code; what-if scenarios try other values without touching these.", "",
           "| Group | Setting | Key | Live | Range | Formula | Used in |", "|---|---|---|---|---|---|---|"]
    for s in SETTINGS:
        live = to_display(s.key, getattr(LIVE, s.key))
        out.append(f"| {groups.get(s.group, s.group)} | {_md_cell(s.label)} | `{s.key}` | {_md_cell(live)} | "
                   f"{_md_cell(to_display(s.key, s.minimum))} to {_md_cell(to_display(s.key, s.maximum))} | "
                   f"{_md_cell(s.formula)} | {_md_cell(s.used_in)} |")
    out += ["", "## Personal preferences", "", "Each person's Preferences (`src/preferences.py`, `SETTINGS_SPEC`), "
            "stored per account in `ui_preferences`. Only values that differ from the default are stored.", "",
            "| Key | Default | Choices |", "|---|---|---|"]
    for key, (default, allowed) in SETTINGS_SPEC.items():
        choices = "true or false" if allowed is bool else ", ".join(map(str, allowed))
        out.append(f"| `{key}` | {default} | {choices} |")
    return "\n".join(out) + "\n"


def dependencies(session) -> str:
    out = ["## Python packages", "", "Pinned in `requirements.txt` (and `requirements-dev.txt` for tests). "
           "A difference between pinned and installed means the environment needs `pip install -r requirements.txt`.",
           "", "| Package | Pinned | Installed |", "|---|---|---|"]
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)", line.strip())
            if not m:
                continue
            try:
                installed = importlib.metadata.version(m.group(1))
            except importlib.metadata.PackageNotFoundError:
                installed = "not installed"
            flag = "" if installed == m.group(2) else " (differs)"
            out.append(f"| {m.group(1)} | {m.group(2)} | {installed}{flag} |")
    pg = session.execute(text("SHOW server_version")).scalar()
    ext = ", ".join(f"{n} {v}" for n, v in session.execute(text("SELECT extname, extversion FROM pg_extension ORDER BY 1")))
    out += ["", "## Database", "", f"PostgreSQL {pg}. Extensions: {ext or 'none'}.", "",
            "## Outside services", "",
            "| Service | Used for | Where in the code | If it fails |", "|---|---|---|---|",
            "| Yahoo Finance (through `yfinance`) | Prices, annual reports, dividends, company profiles, analyst ratings, holders, fund data | `src/ingestion/yahoo_client.py`, `src/etf/` | That night's data isn't updated; pages show the last stored figures and the data chip turns amber. See [Nightly run failed](kb:rb-nightly-run-failed) |",
            "| ASX monthly ETP report (Excel) | ETF and LIC facts, NTA, performance, index returns | `src/etf/asx_report.py` | Last month's facts stay; see [ETF report won't load](kb:rb-asx-report) |",
            "| None in the browser | The pages load nothing from other sites | `web/` | Not applicable |"]
    return "\n".join(out) + "\n"


def test_catalogue() -> str:
    out = ["Every test file, its stated purpose (its opening docstring) and how many tests it holds. Unit tests "
           "need nothing installed; integration tests need PostgreSQL (`tests/conftest.py`).", "",
           "| File | Tests | What it proves |", "|---|---|---|"]
    total = 0
    for f in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        n = sum(1 for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"))
        total += n
        doc = " ".join((ast.get_docstring(tree) or "").split())
        out.append(f"| `{f.relative_to(ROOT).as_posix()}` | {n} | {_md_cell(doc)} |")
    out += ["", f"**{total} test functions** (parametrised tests run more than once, so pytest reports more). "
            "Run them all with `.venv/bin/python -m pytest -q` (Windows: `.venv\\Scripts\\python -m pytest -q`)."]
    return "\n".join(out) + "\n"


def build(name: str, session=None, app=None) -> str:
    if name == "ref-data-dictionary":
        return data_dictionary(session)
    if name == "ref-api":
        return api_reference(app)
    if name == "ref-settings":
        return settings_reference()
    if name == "ref-dependencies":
        return dependencies(session)
    if name == "ref-tests":
        return test_catalogue()
    raise KeyError(name)
