"""Search Sift's database for a name or phrase (read-only).

    .venv\\Scripts\\python.exe scripts\\search_db.py MUFG "Link Market"

Looks, case-insensitively, through every place a company, fund, holder or
registry name can appear: company names and descriptions, Yahoo's top
holders, ETF and LIC fund holdings and descriptions, and the ASX monthly
report rows (including every raw column). Prints each match with where it
was found. Uses the database in .env, like the rest of Sift; changes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from src.config import get_session  # noqa: E402

PLACES = [
    ("Company name", "SELECT asx_code, company_name FROM companies WHERE company_name ILIKE :q"),
    ("Company description", "SELECT asx_code, left(business_summary, 160) FROM companies WHERE business_summary ILIKE :q"),
    ("Top holder (Yahoo)", """SELECT c.asx_code, h.holder_kind || ': ' || h.holder FROM top_holders h
                              JOIN companies c USING (company_id) WHERE h.holder ILIKE :q ORDER BY 1"""),
    ("Fund holding (Yahoo)", """SELECT c.asx_code, f.name FROM fund_holdings f JOIN companies c USING (company_id)
                                WHERE f.name ILIKE :q ORDER BY 1"""),
    ("Fund description", "SELECT c.asx_code, left(p.description, 160) FROM fund_profiles p JOIN companies c USING (company_id) WHERE p.description ILIKE :q"),
    ("ASX monthly report", """SELECT DISTINCT c.asx_code, coalesce(m.fund_name, '') || ' (' || coalesce(m.issuer, '') || ')'
                              FROM etf_monthly m JOIN companies c USING (company_id)
                              WHERE m.fund_name ILIKE :q OR m.issuer ILIKE :q OR m.raw::text ILIKE :q"""),
]


def main(terms: list[str]) -> int:
    if not terms:
        print(__doc__)
        return 1
    with get_session() as session:
        for term in terms:
            print(f'Searching for "{term}"')
            found = 0
            for label, sql in PLACES:
                rows = session.execute(text(sql), {"q": f"%{term}%"}).all()
                for code, detail in rows[:25]:
                    print(f"  {label:22} {code:6} {detail}")
                if len(rows) > 25:
                    print(f"  {label:22} ... and {len(rows) - 25} more")
                found += len(rows)
            print(f"  {found} match{'es' if found != 1 else ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
