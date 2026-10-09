"""Entity records for AI and the graph (docs/kb/features/ai-and-graph.md).

Yahoo gives holders as names and fund holdings as symbols. This turns them
into records: one `managers` row per fund manager, one `holders` row per
fund or institution (with its manager and whether it tracks an index),
`top_holders.holder_id` pointing at the holder, and
`fund_holdings.held_company_id` pointing at the Sift company a fund holds
(matched on its Yahoo symbol, then on its ASX code). Safe to re-run; the
nightly job runs it before the graph export."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from src.coattail.views import is_index_fund, manager_of, slug


@dataclass
class EntityRefresh:
    managers: int
    holders: int
    holdings_linked: int
    fund_lines_matched: int
    fund_lines: int


def refresh(session) -> EntityRefresh:
    """Bring the entity records up to date with the holder and holdings data. The caller commits."""
    rows = session.execute(text("SELECT DISTINCT holder, holder_kind FROM top_holders WHERE holder IS NOT NULL")).all()
    managers: dict[str, str] = {}
    holders = []
    for name, kind in rows:
        manager = manager_of(name)
        managers[slug(manager)] = manager
        holders.append({"name": name, "kind": kind, "manager": slug(manager), "index": is_index_fund(name, kind)})
    if managers:
        session.execute(text("""
            INSERT INTO managers (manager_id, name) VALUES (:id, :name)
            ON CONFLICT (manager_id) DO UPDATE SET name = EXCLUDED.name, updated_at = CURRENT_TIMESTAMP
        """), [{"id": k, "name": v} for k, v in managers.items()])
    if holders:
        session.execute(text("""
            INSERT INTO holders (name, holder_kind, manager_id, index_fund) VALUES (:name, :kind, :manager, :index)
            ON CONFLICT (name) DO UPDATE SET holder_kind = EXCLUDED.holder_kind, manager_id = EXCLUDED.manager_id,
                index_fund = EXCLUDED.index_fund, updated_at = CURRENT_TIMESTAMP
        """), holders)
    linked = session.execute(text("""
        UPDATE top_holders t SET holder_id = h.holder_id FROM holders h
        WHERE h.name = t.holder AND t.holder_id IS DISTINCT FROM h.holder_id
    """)).rowcount or 0
    # A fund's line "BHP.AX" is Sift's BHP; a bare "BHP" too, when Sift has that ASX code.
    session.execute(text("""
        UPDATE fund_holdings f SET held_company_id = c.company_id FROM companies c
        WHERE f.held_company_id IS NULL AND f.symbol IS NOT NULL
          AND (upper(f.symbol) = upper(c.ticker) OR upper(f.symbol) = c.asx_code)
    """))
    matched, total = session.execute(text(
        "SELECT count(held_company_id), count(*) FROM fund_holdings")).one()
    return EntityRefresh(len(managers), len(holders), linked, matched, total)
