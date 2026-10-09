"""What-if runs (docs/AS_BUILT.md §24): the whole screened universe valued,
tested and scored with a scenario's settings, against the same with the
live settings, on today's data. Nothing is written to the database's
market or valuation tables, signals or the track record.

Each company's inputs are gathered once (prices, up to five annual
reports, recent closes) and kept in memory until the data changes, so a
run is a few seconds of arithmetic, not hundreds of queries.

Two things are deliberately kept at their live values in a scenario:
- Margin-of-safety trend (momentum) compares with the live margin of
  safety stored 30 days ago, so a scenario uses the live trend rather
  than comparing its own figure with a live one.
- Held positions and watchlists are today's.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, text

from screen_asx import annotate_row, args_from_settings
from src.accounts import current_user_id
from src.models import Company, Scenario
from src.portfolio.holdings import position_summaries
from src.screening.actions import ACTION_ORDER
from src.screening.enriched import valuation_status
from src.screening.scores import AXES, axis_scores, score_card
from src.settings import BY_KEY, LIVE, ModelSettings, SettingsError, differences, to_display, with_overrides
from src.tracking.signals import ACTION_RANK
from src.valuation.engine import (
    DEFAULT_TREND_DAYS, ValuationInputs, _COLUMN_PRECISION, _average_dividend_per_share,
    _average_free_cash_flow, compute_metrics, gather_inputs,
)

MAX_AVERAGE_YEARS = int(BY_KEY["fcf_average_years"].maximum)
MOS_BINS = ((None, Decimal("-50")), (Decimal("-50"), Decimal("-20")), (Decimal("-20"), Decimal("0")),
            (Decimal("0"), Decimal("20")), (Decimal("20"), Decimal("40")), (Decimal("40"), Decimal("60")),
            (Decimal("60"), None))

_lock = threading.Lock()
_cache: dict = {"key": None, "inputs": []}


@dataclass
class Prepared:
    asx_code: str
    company_name: str | None
    sector: str | None
    inputs: ValuationInputs


def _data_key(session) -> tuple:
    return tuple(session.execute(text("""
        SELECT (SELECT MAX(price_date) FROM daily_prices), (SELECT MAX(as_of_date) FROM valuation_metrics),
               (SELECT COUNT(*) FROM financial_reports), (SELECT COUNT(*) FROM asx_value_screener)
    """)).one())


def prepare(session) -> list[Prepared]:
    """Every screened company's inputs, gathered once per data version."""
    key = _data_key(session)
    with _lock:
        if _cache["key"] == key:
            return _cache["inputs"]
        codes = session.execute(text("SELECT asx_code FROM asx_value_screener")).scalars().all()
        companies = session.execute(select(Company).where(Company.asx_code.in_(codes))).scalars().all() if codes else []
        prepared = []
        for company in sorted(companies, key=lambda c: c.asx_code):
            inputs = gather_inputs(session, company, fcf_average_years=MAX_AVERAGE_YEARS, trend_days=DEFAULT_TREND_DAYS)
            if inputs is not None:
                prepared.append(Prepared(company.asx_code, company.company_name, company.sector, inputs))
        _cache.update(key=key, inputs=prepared)
        return prepared


def with_average_years(inputs: ValuationInputs, years: int) -> ValuationInputs:
    """The same inputs with the base averaged over `years` annual reports."""
    window = (inputs.history_reports or inputs.reports)[:max(years, 1)]
    return replace(inputs, reports=window, dcf_free_cash_flow=_average_free_cash_flow(window),
                   ddm_dividend_per_share=_average_dividend_per_share(window))


def _as_stored(metrics: dict) -> dict:
    """Round each figure to its database column's scale, as the nightly job
    stores it, so a live run here matches the screener to the cent."""
    out = dict(metrics)
    for key, (precision, scale) in _COLUMN_PRECISION.items():
        value = out.get(key)
        if value is None:
            continue
        if abs(value) >= Decimal(10) ** (precision - scale):
            out[key] = None
        else:
            out[key] = value.quantize(Decimal(1).scaleb(-scale))
    return out


def evaluate(prepared: list[Prepared], settings: ModelSettings, positions: dict, today: date,
             momentum_from: dict[str, Decimal | None] | None = None) -> dict[str, dict]:
    """{asx_code: row} for every company, as the screener would show it
    under `settings`."""
    args = args_from_settings(settings)
    rows = {}
    for p in prepared:
        inputs = with_average_years(p.inputs, settings.fcf_average_years)
        metrics = _as_stored(compute_metrics(inputs, settings=settings))
        row = {"asx_code": p.asx_code, "company_name": p.company_name, "sector": p.sector,
               "current_price": p.inputs.price.close_price} | metrics
        if momentum_from is not None:
            row["margin_of_safety_trend"] = momentum_from.get(p.asx_code)
        row = annotate_row(row, args, positions.get(p.asx_code), today, settings)
        row["axis_scores"] = axis_scores(score_card(row, p.inputs.report, settings))
        row["valuation_status"] = valuation_status(row["margin_of_safety_percent"], settings.min_margin_of_safety)
        rows[p.asx_code] = row
    return rows


def _bin(mos: Decimal | None) -> int | None:
    if mos is None:
        return None
    for i, (low, high) in enumerate(MOS_BINS):
        if (low is None or mos >= low) and (high is None or mos < high):
            return i
    return None


def _brief(code: str, live: dict, new: dict, watched: dict[str, list[str]]) -> dict:
    return {
        "asx_code": code, "company_name": live["company_name"], "sector": live["sector"],
        "held": live["held"] is not None, "watchlists": watched.get(code, []),
        "price": live["current_price"],
        "live_action": live["action"], "action": new["action"], "action_reason": new["action_reason"],
        "live_status": live["valuation_status"], "status": new["valuation_status"],
        "live_value": live["dcf_intrinsic_value"], "value": new["dcf_intrinsic_value"],
        "live_mos": live["margin_of_safety_percent"], "mos": new["margin_of_safety_percent"],
        "live_score": sum(live["axis_scores"].values()), "score": sum(new["axis_scores"].values()),
        "direction": ("up" if ACTION_RANK.get(new["action"], 4) < ACTION_RANK.get(live["action"], 4)
                      else "down" if ACTION_RANK.get(new["action"], 4) > ACTION_RANK.get(live["action"], 4) else "same"),
    }


def compare(live: dict[str, dict], new: dict[str, dict], watched: dict[str, list[str]]) -> dict:
    """What the scenario changes: action counts, moves between actions,
    the companies whose action or valuation status changes, your holdings
    and watchlists, and the spread of margins of safety."""
    codes = sorted(live)
    counts = {a: [sum(1 for c in codes if live[c]["action"] == a), sum(1 for c in codes if new[c]["action"] == a)]
              for a in ACTION_ORDER}
    moves = Counter((live[c]["action"], new[c]["action"]) for c in codes if live[c]["action"] != new[c]["action"])
    changed = [_brief(c, live[c], new[c], watched) for c in codes
               if live[c]["action"] != new[c]["action"] or live[c]["valuation_status"] != new[c]["valuation_status"]]
    changed.sort(key=lambda b: ({"up": 0, "down": 1, "same": 2}[b["direction"]], ACTION_RANK.get(b["action"], 4), b["asx_code"]))
    mine = [_brief(c, live[c], new[c], watched) for c in codes if live[c]["held"] is not None or watched.get(c)]
    bins = [[0, 0] for _ in MOS_BINS]
    for c in codes:
        for k, rows in enumerate((live, new)):
            b = _bin(rows[c]["margin_of_safety_percent"])
            if b is not None:
                bins[b][k] += 1

    def median_mos(rows):
        values = sorted(r["margin_of_safety_percent"] for r in rows.values() if r["margin_of_safety_percent"] is not None)
        return values[len(values) // 2] if values else None

    def avg_score(rows):
        return sum(sum(r["axis_scores"].values()) for r in rows.values()) / len(rows) if rows else None

    return {
        "companies": len(codes),
        "counts": [{"action": a, "live": l, "scenario": s} for a, (l, s) in counts.items() if l or s],
        "moves": [{"from": f, "to": t, "companies": n} for (f, t), n in sorted(moves.items(), key=lambda m: -m[1])],
        "changed": changed,
        "mine": mine,
        "distribution": [{"low": low, "high": high, "live": l, "scenario": s} for (low, high), (l, s) in zip(MOS_BINS, bins)],
        "summary": {"median_mos": [median_mos(live), median_mos(new)], "average_score": [avg_score(live), avg_score(new)],
                    "valued": [sum(1 for r in live.values() if r["dcf_intrinsic_value"] is not None),
                               sum(1 for r in new.values() if r["dcf_intrinsic_value"] is not None)]},
    }


def run(session, settings: ModelSettings, today: date, watched: dict[str, list[str]]) -> dict:
    """A scenario against live, on today's data."""
    prepared = prepare(session)
    positions = position_summaries(session, today)
    live = evaluate(prepared, LIVE, positions, today)
    momentum = {code: row["margin_of_safety_trend"] for code, row in live.items()}
    new = live if settings == LIVE else evaluate(prepared, settings, positions, today, momentum_from=momentum)
    changes = differences(settings)
    return {
        "changes": [{"key": k, "label": BY_KEY[k].label, "unit": BY_KEY[k].unit, "help_id": BY_KEY[k].help_id,
                     "live": to_display(k, a), "scenario": to_display(k, b)} for k, (a, b) in changes.items()],
        "axes": list(AXES),
        **compare(live, new, watched),
    }


# ---------- saved scenarios ----------

class ScenarioError(ValueError):
    """A request that breaks a rule; the message is written for the user."""


def _clean(session, name, notes, overrides, except_id=None) -> dict:
    name = " ".join(str(name or "").split())
    if not name:
        raise ScenarioError("A scenario needs a name")
    if len(name) > 60:
        raise ScenarioError("Scenario names can be at most 60 characters")
    clash = session.execute(select(Scenario).where(
        Scenario.owner_id == current_user_id(session), func.lower(Scenario.name) == name.lower())).scalar_one_or_none()
    if clash is not None and clash.scenario_id != except_id:
        raise ScenarioError(f"There is already a scenario called {clash.name!r}")
    notes = str(notes or "").strip() or None
    if notes and len(notes) > 1000:
        raise ScenarioError("Notes can be at most 1,000 characters")
    kept = {k: str(v).strip() for k, v in (overrides or {}).items() if v is not None and str(v).strip() != ""}
    try:
        settings = with_overrides(kept)
    except SettingsError as exc:
        raise ScenarioError(str(exc)) from None
    # Keep only real changes, as entered, so the scenario reads back the way it was typed.
    changed = differences(settings)
    return {"name": name, "notes": notes, "overrides": {k: v for k, v in kept.items() if k in changed}}


def save_scenario(session, name, notes, overrides, scenario=None):
    fields = _clean(session, name, notes, overrides, scenario.scenario_id if scenario else None)
    if scenario is None:
        scenario = Scenario(**fields, owner_id=current_user_id(session))
        session.add(scenario)
    else:
        scenario.name, scenario.notes, scenario.overrides = fields["name"], fields["notes"], fields["overrides"]
    session.flush()
    return scenario


def list_scenarios(session, order=("name",)):
    """The current user's saved scenarios."""
    columns = {"name": Scenario.name, "updated": Scenario.updated_at.desc()}
    return list(session.execute(select(Scenario).where(Scenario.owner_id == current_user_id(session))
                                .order_by(*(columns[c] for c in order))).scalars())


def get_scenario(session, scenario_id):
    """One of the current user's scenarios by ID, or None."""
    try:
        found = session.get(Scenario, uuid.UUID(str(scenario_id)))
    except ValueError:
        return None
    return found if found is not None and found.owner_id == current_user_id(session) else None


def scenario_settings(scenario) -> ModelSettings:
    return with_overrides(scenario.overrides or {})
