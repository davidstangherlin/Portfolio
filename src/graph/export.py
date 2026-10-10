"""Export Sift as a graph for Neo4j (docs/kb/features/ai-and-graph.md).

PostgreSQL stays the source of truth; this writes a snapshot as CSV files
plus `load.cypher`, which loads them into Neo4j (Desktop or Aura) with
MERGE, so loading again updates rather than duplicates. Nodes:

  Company (also :Share, :ETF or :LIC), Sector, Category, Manager, Holder
  (also :Fund or :Institution), and with personal data: User, Portfolio,
  Watchlist.

Relationships:

  (Company)-[:IN_SECTOR]->(Sector), (Company)-[:IN_CATEGORY]->(Category),
  (Holder)-[:MANAGED_BY]->(Manager), (Holder)-[:HOLDS]->(Company),
  (Company)-[:FUND_HOLDS]->(Company) for an ETF or LIC's holdings, and
  (User)-[:OWNS]->(Portfolio|Watchlist), (Portfolio)-[:HOLDS_POSITION]->(Company),
  (Watchlist)-[:WATCHES]->(Company).

Personal data (people, portfolios, watchlists) is included unless
`personal=False`; the files then hold portfolios, so they're written to
data/graph/, which git ignores.

    python -m src.graph.export                 # everything, to data/graph/
    python -m src.graph.export --shared-only   # market, holders and funds only
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from src import version
from src.coattail.views import slug
from src.graph import entities

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "graph"
logger = logging.getLogger(__name__)


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral() else str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _write(folder: Path, name: str, header: list[str], rows) -> int:
    n = 0
    with open(folder / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([_cell(r.get(h)) for h in header])
            n += 1
    return n


def _rows(session, sql: str, **params) -> list[dict]:
    return [dict(r) for r in session.execute(text(sql), params).mappings()]


def companies(session, today: date) -> list[dict]:
    """Every company, ETF and LIC with Sift's shared call (for someone not holding it) on shares."""
    from src.screening.enriched import load_universe
    from src.screening.scores import AXES

    calls = {r["asx_code"]: r for r in load_universe(session, today, neutral=True).rows}
    funds = {r["asx_code"]: r for r in _rows(session, """
        SELECT DISTINCT ON (c.asx_code) c.asx_code, e.issuer, e.category, e.mer_percent, e.fum_aud, e.benchmark
        FROM etf_monthly e JOIN companies c USING (company_id) ORDER BY c.asx_code, e.report_month DESC""")}
    out = []
    from src.registries import describe
    for c in _rows(session, """SELECT company_id, asx_code, company_name, security_type, sector, industry, country, is_active,
                                      registry_id, registry_name
                               FROM companies ORDER BY asx_code"""):
        r = calls.get(c["asx_code"]) or {}
        f = funds.get(c["asx_code"]) or {}
        scores = r.get("axis_scores") or {}
        out.append({
            "id": c["asx_code"], "name": c["company_name"], "type": c["security_type"], "sector": c["sector"],
            "industry": c["industry"], "country": c["country"], "active": c["is_active"],
            "price": r.get("current_price"), "estimated_value": r.get("dcf_intrinsic_value"),
            "valuation_method": r.get("valuation_method"), "margin_of_safety": r.get("margin_of_safety_percent"),
            "valuation_status": r.get("valuation_status"), "action": r.get("action"), "action_reason": r.get("action_reason"),
            "score": sum(scores.values()) if scores else None, **{f"score_{a.lower()}": scores.get(a) for a in AXES},
            "as_of": r.get("as_of_date"), "issuer": f.get("issuer"), "category": f.get("category"),
            "fee_percent": f.get("mer_percent"), "fund_size_aud": f.get("fum_aud"), "benchmark": f.get("benchmark"),
            "registry": (describe(c["registry_id"], c["registry_name"]) or {}).get("name"),
        })
    return out


def export(session, out_dir: Path = OUT_DIR, personal: bool = True, today: date | None = None) -> dict:
    """Write the graph to `out_dir` and return the manifest (also written as manifest.json)."""
    from src.screening.scores import AXES

    today = today or date.today()
    ent = entities.refresh(session)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.csv"):
        old.unlink()
    counts: dict[str, int] = {}

    comp = companies(session, today)
    head = ["id", "name", "type", "sector", "industry", "country", "active", "price", "estimated_value", "valuation_method",
            "margin_of_safety", "valuation_status", "action", "action_reason", "score",
            *[f"score_{a.lower()}" for a in AXES], "as_of", "issuer", "category", "fee_percent", "fund_size_aud", "benchmark", "registry"]
    counts["companies"] = _write(out_dir, "companies.csv", head, comp)
    sectors = sorted({c["sector"] for c in comp if c["sector"]})
    counts["sectors"] = _write(out_dir, "sectors.csv", ["id", "name"], ({"id": slug(s), "name": s} for s in sectors))
    cats = sorted({c["category"] for c in comp if c["category"]})
    counts["categories"] = _write(out_dir, "categories.csv", ["id", "name"], ({"id": slug(s), "name": s} for s in cats))
    counts["in_sector"] = _write(out_dir, "in_sector.csv", ["company", "sector"],
                                 ({"company": c["id"], "sector": slug(c["sector"])} for c in comp if c["sector"]))
    counts["in_category"] = _write(out_dir, "in_category.csv", ["company", "category"],
                                   ({"company": c["id"], "category": slug(c["category"])} for c in comp if c["category"]))
    counts["managers"] = _write(out_dir, "managers.csv", ["id", "name"],
                                _rows(session, "SELECT manager_id AS id, name FROM managers ORDER BY 1"))
    counts["holders"] = _write(out_dir, "holders.csv", ["id", "name", "kind", "index_fund", "manager"], _rows(session, """
        SELECT holder_id AS id, name, holder_kind AS kind, index_fund, manager_id AS manager FROM holders ORDER BY name"""))
    counts["holds"] = _write(out_dir, "holds.csv", ["holder", "company", "shares", "percent_held", "value", "percent_change", "reported"],
                             _rows(session, """
        SELECT t.holder_id AS holder, c.asx_code AS company, t.shares, t.percent_held, t.value, t.percent_change, t.date_reported AS reported
        FROM top_holders t JOIN companies c USING (company_id) WHERE t.holder_id IS NOT NULL"""))
    counts["fund_holds"] = _write(out_dir, "fund_holds.csv", ["fund", "company", "weight_percent", "rank"], _rows(session, """
        SELECT f.asx_code AS fund, h.asx_code AS company, fh.weight_percent, fh.rank
        FROM fund_holdings fh JOIN companies f ON f.company_id = fh.company_id
        JOIN companies h ON h.company_id = fh.held_company_id"""))
    # ASX notices (docs/kb/features/coattail.md): directors' trades and substantial holders, for Sift's companies.
    trades = _rows(session, """
        SELECT t.notice_id AS notice, c.asx_code AS company, t.director, t.change_date AS date, t.direction,
               t.acquired, t.disposed, t.consideration AS value, t.price, t.nature_kind AS nature
        FROM director_trades t JOIN asx_notices n USING (notice_id) JOIN companies c ON c.company_id = n.company_id
        WHERE t.director IS NOT NULL ORDER BY n.released_at, t.notice_id, t.line_no""")
    for t in trades:
        t["id"] = slug(f"{t['company']} {t['director']}")  # a director is known by name within their company
    counts["directors"] = _write(out_dir, "directors.csv", ["id", "name", "company"],
                                 {t["id"]: {"id": t["id"], "name": t["director"], "company": t["company"]} for t in trades}.values())
    counts["director_trades"] = _write(out_dir, "director_trades.csv", ["id", "company", "notice", "date", "direction", "acquired",
                                                                         "disposed", "value", "price", "nature"], trades)
    counts["substantial"] = _write(out_dir, "substantial.csv", ["manager", "manager_name", "company", "notice", "event", "date",
                                                                 "previous_pct", "present_pct"], ({**r, "manager": slug(r["manager_name"])} for r in _rows(session, """
        SELECT s.manager AS manager_name, c.asx_code AS company, s.notice_id AS notice, n.kind AS event, s.event_date AS date,
               s.previous_pct, s.present_pct
        FROM substantial_holdings s JOIN asx_notices n USING (notice_id) JOIN companies c ON c.company_id = n.company_id
        WHERE s.manager IS NOT NULL ORDER BY n.released_at""")))
    if personal:
        counts["users"] = _write(out_dir, "users.csv", ["id", "name", "role"], _rows(session, """
            SELECT user_id AS id, display_name AS name, role FROM users WHERE status = 'active' ORDER BY created_at"""))
        counts["portfolios"] = _write(out_dir, "portfolios.csv", ["id", "owner", "name", "tax_type", "archived"], _rows(session, """
            SELECT portfolio_id AS id, owner_id AS owner, name, tax_type, archived_at IS NOT NULL AS archived FROM portfolios"""))
        counts["positions"] = _write(out_dir, "positions.csv", ["portfolio", "company", "units", "cost_base", "first_bought"], _rows(session, """
            SELECT h.portfolio_id AS portfolio, c.asx_code AS company, sum(h.units) AS units,
                   round(sum(h.units * h.buy_price + h.buy_brokerage), 2) AS cost_base, min(h.buy_date) AS first_bought
            FROM holdings h JOIN companies c ON c.asx_code = h.asx_code
            WHERE h.sell_date IS NULL GROUP BY h.portfolio_id, c.asx_code"""))
        counts["watchlists"] = _write(out_dir, "watchlists.csv", ["id", "owner", "name"], _rows(session, """
            SELECT watchlist_id AS id, owner_id AS owner, name FROM watchlists"""))
        counts["watches"] = _write(out_dir, "watches.csv", ["watchlist", "company", "note"], _rows(session, """
            SELECT i.watchlist_id AS watchlist, c.asx_code AS company, i.note
            FROM watchlist_items i JOIN companies c USING (company_id)"""))
    (out_dir / "load.cypher").write_text(load_script(personal), encoding="utf-8")
    manifest = {"sift_version": version.VERSION, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "market_date": str(today), "personal": personal, "counts": counts,
                "fund_lines_matched": f"{ent.fund_lines_matched} of {ent.fund_lines}"}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def load_script(personal: bool) -> str:
    """Cypher that loads the CSV files (copied into Neo4j's import folder). Safe to run again."""
    nodes = [
        ("Company", "companies.csv", "c", "id",
         "SET c.name = row.name, c.type = row.type, c.sector = row.sector, c.industry = row.industry, c.country = row.country, "
         "c.active = row.active = 'true', c.price = toFloatOrNull(row.price), c.estimated_value = toFloatOrNull(row.estimated_value), "
         "c.valuation_method = row.valuation_method, c.margin_of_safety = toFloatOrNull(row.margin_of_safety), "
         "c.valuation_status = row.valuation_status, c.action = row.action, c.action_reason = row.action_reason, "
         "c.score = toIntegerOrNull(row.score), c.as_of = CASE row.as_of WHEN '' THEN null ELSE date(row.as_of) END, "
         "c.issuer = row.issuer, c.category = row.category, c.fee_percent = toFloatOrNull(row.fee_percent), "
         "c.fund_size_aud = toFloatOrNull(row.fund_size_aud), c.benchmark = row.benchmark, "
         "c.registry = CASE row.registry WHEN '' THEN null ELSE row.registry END "
         "FOREACH (_ IN CASE WHEN row.type = 'SHARE' THEN [1] ELSE [] END | SET c:Share) "
         "FOREACH (_ IN CASE WHEN row.type = 'ETF' THEN [1] ELSE [] END | SET c:ETF) "
         "FOREACH (_ IN CASE WHEN row.type = 'LIC' THEN [1] ELSE [] END | SET c:LIC)"),
        ("Sector", "sectors.csv", "s", "id", "SET s.name = row.name"),
        ("Category", "categories.csv", "k", "id", "SET k.name = row.name"),
        ("Manager", "managers.csv", "m", "id", "SET m.name = row.name"),
        ("Holder", "holders.csv", "h", "id",
         "SET h.name = row.name, h.kind = row.kind, h.index_fund = row.index_fund = 'true' "
         "FOREACH (_ IN CASE WHEN row.kind = 'FUND' THEN [1] ELSE [] END | SET h:Fund) "
         "FOREACH (_ IN CASE WHEN row.kind = 'INSTITUTION' THEN [1] ELSE [] END | SET h:Institution)"),
        ("Director", "directors.csv", "d", "id", "SET d.name = row.name"),
        # Substantial holders join the managers from the holder lists, or become managers of their own.
        ("Manager", "substantial.csv", "m", "manager", "SET m.name = coalesce(m.name, row.manager_name)"),
    ]
    rels = [
        ("in_sector.csv", "MATCH (a:Company {id: row.company}), (b:Sector {id: row.sector}) MERGE (a)-[:IN_SECTOR]->(b)"),
        ("in_category.csv", "MATCH (a:Company {id: row.company}), (b:Category {id: row.category}) MERGE (a)-[:IN_CATEGORY]->(b)"),
        ("holders.csv", "MATCH (a:Holder {id: row.id}), (b:Manager {id: row.manager}) MERGE (a)-[:MANAGED_BY]->(b)"),
        ("holds.csv", "MATCH (a:Holder {id: row.holder}), (b:Company {id: row.company}) MERGE (a)-[r:HOLDS]->(b) "
                      "SET r.shares = toFloatOrNull(row.shares), r.percent_held = toFloatOrNull(row.percent_held), "
                      "r.value = toFloatOrNull(row.value), r.percent_change = toFloatOrNull(row.percent_change), "
                      "r.reported = CASE row.reported WHEN '' THEN null ELSE date(row.reported) END"),
        ("fund_holds.csv", "MATCH (a:Company {id: row.fund}), (b:Company {id: row.company}) MERGE (a)-[r:FUND_HOLDS]->(b) "
                           "SET r.weight_percent = toFloatOrNull(row.weight_percent), r.rank = toIntegerOrNull(row.rank)"),
        ("directors.csv", "MATCH (a:Director {id: row.id}), (b:Company {id: row.company}) MERGE (a)-[:DIRECTOR_OF]->(b)"),
        ("director_trades.csv", "MATCH (a:Director {id: row.id}), (b:Company {id: row.company}) MERGE (a)-[r:TRADED {notice: row.notice}]->(b) "
                                "SET r.date = CASE row.date WHEN '' THEN null ELSE date(row.date) END, r.direction = row.direction, "
                                "r.acquired = toFloatOrNull(row.acquired), r.disposed = toFloatOrNull(row.disposed), "
                                "r.value = toFloatOrNull(row.value), r.price = toFloatOrNull(row.price), r.nature = row.nature"),
        ("substantial.csv", "MATCH (a:Manager {id: row.manager}), (b:Company {id: row.company}) MERGE (a)-[r:SUBSTANTIAL_NOTICE {notice: row.notice}]->(b) "
                            "SET r.event = row.event, r.date = CASE row.date WHEN '' THEN null ELSE date(row.date) END, "
                            "r.previous_pct = toFloatOrNull(row.previous_pct), r.present_pct = toFloatOrNull(row.present_pct)"),
    ]
    if personal:
        nodes += [("User", "users.csv", "u", "id", "SET u.name = row.name, u.role = row.role"),
                  ("Portfolio", "portfolios.csv", "p", "id", "SET p.name = row.name, p.tax_type = row.tax_type, p.archived = row.archived = 'true'"),
                  ("Watchlist", "watchlists.csv", "w", "id", "SET w.name = row.name")]
        rels += [("portfolios.csv", "MATCH (a:User {id: row.owner}), (b:Portfolio {id: row.id}) MERGE (a)-[:OWNS]->(b)"),
                 ("watchlists.csv", "MATCH (a:User {id: row.owner}), (b:Watchlist {id: row.id}) MERGE (a)-[:OWNS]->(b)"),
                 ("positions.csv", "MATCH (a:Portfolio {id: row.portfolio}), (b:Company {id: row.company}) MERGE (a)-[r:HOLDS_POSITION]->(b) "
                                   "SET r.units = toFloatOrNull(row.units), r.cost_base = toFloatOrNull(row.cost_base), "
                                   "r.first_bought = date(row.first_bought)"),
                 ("watches.csv", "MATCH (a:Watchlist {id: row.watchlist}), (b:Company {id: row.company}) MERGE (a)-[r:WATCHES]->(b) "
                                 "SET r.note = row.note")]
    lines = ["// Sift graph, generated by src/graph/export.py. Copy this folder's CSV files into Neo4j's import",
             "// folder, then run this script (Neo4j Browser: paste it; cypher-shell: -f load.cypher). Safe to run again.", ""]
    lines += [f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE;"
              for label in dict.fromkeys(label for label, *_ in nodes)]
    lines.append("")
    for label, file, var, key, sets in nodes:
        lines.append(f"LOAD CSV WITH HEADERS FROM 'file:///{file}' AS row MERGE ({var}:{label} {{id: row.{key}}}) {sets};")
    for file, body in rels:
        lines.append(f"LOAD CSV WITH HEADERS FROM 'file:///{file}' AS row {body};")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from src.config import get_session

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Export Sift as a graph for Neo4j (CSV files and load.cypher).")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help=f"folder to write to (default {OUT_DIR})")
    parser.add_argument("--shared-only", action="store_true", help="leave out people, portfolios and watchlists")
    args = parser.parse_args(argv)
    with get_session() as session:
        manifest = export(session, args.out, personal=not args.shared_only)
        session.commit()  # the entity records
    logger.info("Graph exported to %s: %s; fund holdings matched to companies %s", args.out,
                ", ".join(f"{k} {v}" for k, v in manifest["counts"].items()), manifest["fund_lines_matched"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
