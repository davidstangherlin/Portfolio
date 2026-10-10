"""Each company's share registry (docs/kb/features/drp-and-registry.md).

A share registry keeps a listed company's register of shareholders and runs
its dividend reinvestment plan (DRP): it's where you log in to see your
holding, change your DRP choice or update bank details. A few registries
run almost every ASX company's register.

Sift reads each company's registry from ASX's company details during the
share download (`refresh()`, a batch each night so every company is checked
about monthly), recognising the registry by name (`match()`). An admin can
set or correct it on the company page; a company set by an admin is never
overwritten.

    python -m src.registries             # check the companies due
    python -m src.registries --dry-run   # check a few, print, save nothing
    python -m src.registries --codes BHP CBA

ASX turns away plain scripted requests, so pages are fetched with a
browser's fingerprint (as the ETF report and ASX notices are)."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass

from sqlalchemy import text

logger = logging.getLogger(__name__)

PAUSE = 1.0          # seconds between requests to ASX
CHECK_DAYS = 30      # a company's registry is checked about monthly
BATCH = 120          # companies checked a night (about 2,000 in a month)


@dataclass(frozen=True)
class Registry:
    registry_id: str
    name: str
    portal: str          # where shareholders log in (opens in a new tab)
    website: str
    pattern: str         # how ASX or a person might write its name


# The registries behind nearly every ASX company. Check the links each year
# (docs/kb/improvements.json): registries rename their portals.
REGISTRIES = [
    Registry("computershare", "Computershare", "https://www-au.computershare.com/Investor/",
             "https://www.computershare.com/au", r"computershare"),
    Registry("mufg", "MUFG Corporate Markets (formerly Link Market Services)", "https://au.investorcentre.mpms.mufg.com/",
             "https://www.mpms.mufg.com/", r"mufg|link\s*market\s*services|link\s*group|link\s*registries"),
    Registry("automic", "Automic Group", "https://investor.automic.com.au/", "https://www.automicgroup.com.au/",
             r"automic|security\s*transfer\s*australia"),
    Registry("boardroom", "BoardRoom", "https://www.investorserve.com.au/", "https://www.boardroomlimited.com.au/",
             r"board\s*room"),
    Registry("advanced", "Advanced Share Registry (part of Automic Group)", "https://www.advancedshare.com.au/",
             "https://www.advancedshare.com.au/", r"advanced\s*share"),
    Registry("xcend", "Xcend", "https://www.xcend.co/", "https://www.xcend.co/", r"xcend"),
]
BY_ID = {r.registry_id: r for r in REGISTRIES}
_PATTERNS = [(r, re.compile(r.pattern, re.I)) for r in REGISTRIES]


def match(name: str | None) -> Registry | None:
    """The known registry a name refers to ("Link Market Services Limited" is MUFG)."""
    for registry, pattern in _PATTERNS:
        if pattern.search(name or ""):
            return registry
    return None


def describe(registry_id: str | None, name: str | None) -> dict | None:
    """The registry card's facts for a company's stored registry."""
    known = BY_ID.get(registry_id or "") or match(name)
    if known:
        return {"registry_id": known.registry_id, "name": known.name, "portal": known.portal, "website": known.website}
    if name:
        return {"registry_id": None, "name": name, "portal": None, "website": None}
    return None


# ---------- reading ASX's company details ----------
ASX_SOURCES = (
    "https://asx.api.markitdigital.com/asx-research/1.0/companies/{code}/about",
    "https://www.asx.com.au/asx/1/company/{code}?fields=primary_share",
)


def get(url: str) -> tuple[int, bytes]:
    time.sleep(PAUSE)
    try:
        from curl_cffi import requests as http
        r = http.get(url, impersonate="chrome", timeout=30)
        return r.status_code, r.content
    except ImportError:
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return r.status, r.read()
        except HTTPError as e:
            return e.code, b""
        except OSError:
            return 0, b""
    except Exception:  # noqa: BLE001 - a network failure is reported, not fatal
        logger.debug("Request failed: %s", url, exc_info=True)
        return 0, b""


def _registry_text(data) -> str | None:
    """The registry's name from ASX's company details: a field whose key
    mentions the registry (a name inside it, or the text itself)."""
    if isinstance(data, dict):
        for key, value in data.items():
            if "regist" in key.lower():
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    for k in ("name", "displayName", "registryName", "company"):
                        if isinstance(value.get(k), str) and value[k].strip():
                            return value[k].strip()
        for value in data.values():
            found = _registry_text(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _registry_text(value)
            if found:
                return found
    return None


def read_registry(body: bytes) -> str | None:
    """The registry named in one ASX response: from its registry field, or
    else the first known registry mentioned anywhere in it."""
    try:
        named = _registry_text(json.loads(body))
    except ValueError:
        named = None
    if named:
        return named[:160]
    known = match(body.decode("utf-8", "replace"))
    return known.name if known else None


def lookup(code: str, fetch=None) -> str | None:
    fetch = fetch or get
    for source in ASX_SOURCES:
        status, body = fetch(source.format(code=code.lower() if "markitdigital" in source else code.upper()))
        if status == 200 and body:
            found = read_registry(body)
            if found:
                return found
    return None


# ---------- storing ----------
def due(session, limit: int = BATCH, codes: list[str] | None = None) -> list[str]:
    if codes:
        return [c.upper() for c in codes]
    return [c for (c,) in session.execute(text("""
        SELECT asx_code FROM companies
        WHERE is_active AND security_type = 'SHARE' AND coalesce(registry_source, '') <> 'admin'
          AND (registry_checked_at IS NULL OR registry_checked_at < CURRENT_TIMESTAMP - make_interval(days => :d))
        ORDER BY registry_checked_at NULLS FIRST, asx_code LIMIT :n"""), {"d": CHECK_DAYS, "n": limit})]


def save_found(session, code: str, name: str | None) -> None:
    """Store what ASX says (or that it said nothing, so the company waits a
    month); never over an admin's choice."""
    known = match(name)
    session.execute(text("""
        UPDATE companies SET registry_checked_at = CURRENT_TIMESTAMP,
               registry_id = CASE WHEN CAST(:name AS TEXT) IS NULL THEN registry_id ELSE :rid END,
               registry_name = coalesce(CAST(:name AS TEXT), registry_name),
               registry_source = CASE WHEN CAST(:name AS TEXT) IS NULL THEN registry_source ELSE 'asx' END
        WHERE asx_code = :code AND coalesce(registry_source, '') <> 'admin'"""),
        {"code": code, "name": name, "rid": known.registry_id if known else None})


class RegistryError(ValueError):
    """A request that breaks a rule; the message is written for the user."""


def set_by_admin(session, code: str, registry_id: str | None, name: str | None = None) -> dict | None:
    """An admin's choice for a company: a known registry, another by name,
    or neither (back to what ASX says, checked on the next run)."""
    name = " ".join((name or "").split())[:160] or None
    if registry_id and registry_id not in BY_ID:
        raise RegistryError("unknown registry")
    if registry_id is None and name is None:
        session.execute(text("""UPDATE companies SET registry_source = NULL, registry_checked_at = NULL
                                WHERE asx_code = :c"""), {"c": code})
        return None
    known = BY_ID.get(registry_id or "") or match(name)
    session.execute(text("""
        UPDATE companies SET registry_id = :rid, registry_name = :name, registry_source = 'admin',
               registry_checked_at = CURRENT_TIMESTAMP WHERE asx_code = :c"""),
        {"c": code, "rid": known.registry_id if known else None, "name": known.name if known else name})
    return describe(known.registry_id if known else None, name)


def company_registry(session, company_id) -> dict:
    row = session.execute(text("""
        SELECT registry_id, registry_name, registry_source, registry_checked_at FROM companies WHERE company_id = :c"""),
        {"c": company_id}).mappings().first()
    facts = describe(row["registry_id"], row["registry_name"]) if row else None
    return {"registry": facts, "source": row["registry_source"] if row else None,
            "checked_at": row["registry_checked_at"] if row else None,
            "choices": [{"registry_id": r.registry_id, "name": r.name} for r in REGISTRIES]}


def refresh(session, limit: int = BATCH, codes: list[str] | None = None, fetch=None, dry_run: bool = False) -> dict:
    found = missing = 0
    for code in due(session, limit, codes):
        name = lookup(code, fetch)
        if dry_run:
            print(f"{code:<6} {name or 'not found'}{f'  ->  {match(name).name}' if match(name) else ''}")
        else:
            save_found(session, code, name)
            session.commit()
        found += bool(name)
        missing += not name
    return {"found": found, "not_found": missing}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Read each company's share registry from ASX.")
    p.add_argument("--dry-run", action="store_true", help="check a few companies, print what ASX says, save nothing")
    p.add_argument("--codes", nargs="+", metavar="CODE", help="these companies only")
    p.add_argument("--limit", type=int, default=None, help=f"companies to check (default {BATCH}; 5 in a dry run)")
    args = p.parse_args(argv)
    from src.config import get_session
    with get_session() as session:
        counts = refresh(session, args.limit or (5 if args.dry_run else BATCH), args.codes, dry_run=args.dry_run)
    logger.info("Share registries: %d found, %d not found", counts["found"], counts["not_found"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
