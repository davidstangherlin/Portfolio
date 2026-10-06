"""The model settings registry (docs/AS_BUILT.md §24): every adjustable
assumption and threshold behind Sift's valuations, tests, markers, actions
and score wheel, in one place.

`LIVE` holds the values the nightly job uses. The modules that apply them
(src/valuation/, src/screening/, screen_asx.py) take their defaults from
here, so this file is the single source of each live value. The admin
console's what-if lab (src/admin/scenarios.py) runs the same calculations
with a copy of these settings changed; it never alters `LIVE`.

`SETTINGS` describes each one for the admin console: its group, label,
unit, allowed range, the formula it feeds, where it's used, and the
knowledge base entry (web/knowledge.json) that explains the concept.

Pure data: imports nothing from the rest of the project, so anything can
import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from decimal import Decimal, InvalidOperation

D = Decimal


@dataclass(frozen=True)
class ModelSettings:
    # Valuation models
    dcf_growth_rate: Decimal = D("0.08")
    ddm_growth_rate: Decimal = D("0.05")
    discount_rate: Decimal = D("0.09")
    terminal_growth_rate: Decimal = D("0.025")
    stage1_years: int = 5
    fcf_average_years: int = 3
    # The four value tests
    min_margin_of_safety: Decimal = D("20")
    min_roe: Decimal = D("12")
    max_debt_equity: Decimal = D("0.80")
    min_yield: Decimal = D("4.5")
    # Markers and actions
    earnings_quality_strong: Decimal = D("100")
    earnings_quality_adequate: Decimal = D("80")
    new_lows_range: Decimal = D("10")
    dividend_cut_ratio: Decimal = D("0.9")
    dividend_growth_ratio: Decimal = D("1.05")
    roe_trend_points: Decimal = D("2")
    revenue_trend_ratio: Decimal = D("0.05")
    min_mos_trend: Decimal = D("5")
    payout_warning: Decimal = D("150")
    overvalued_review: Decimal = D("-50")
    # Score wheel (the checks that don't simply reuse a value test)
    score_mos_strong: Decimal = D("40")
    score_max_pe: Decimal = D("15")
    score_max_pb: Decimal = D("1.5")
    score_roe_high: Decimal = D("20")
    score_min_roic: Decimal = D("10")
    score_debt_equity_low: Decimal = D("0.4")
    score_yield_high: Decimal = D("6")
    score_max_payout: Decimal = D("100")
    score_upper_range: Decimal = D("50")


LIVE = ModelSettings()

GROUPS = (
    ("valuation", "Valuation models"),
    ("tests", "The four value tests"),
    ("markers", "Markers and actions"),
    ("score", "Score wheel"),
)


@dataclass(frozen=True)
class Setting:
    key: str
    group: str
    label: str
    unit: str           # "%" (stored as a percent), "rate" (stored as a fraction, shown as %), "x", "years", "points", "ratio"
    minimum: Decimal
    maximum: Decimal
    formula: str
    used_in: str
    help_id: str        # web/knowledge.json entry explaining the concept


SETTINGS: tuple[Setting, ...] = (
    Setting("dcf_growth_rate", "valuation", "DCF growth rate, years 1 to 5", "rate", D("-0.10"), D("0.30"),
            "Free cash flow grows by this each year in stage 1", "Estimated value for most companies", "growth-rate"),
    Setting("ddm_growth_rate", "valuation", "DDM dividend growth rate, years 1 to 5", "rate", D("-0.10"), D("0.30"),
            "Dividends grow by this each year in stage 1", "Estimated value for banks, insurers and REITs", "growth-rate"),
    Setting("discount_rate", "valuation", "Discount rate", "rate", D("0.03"), D("0.25"),
            "Each future year is divided by (1 + discount rate) ^ years ahead", "Both valuation models", "discount-rate"),
    Setting("terminal_growth_rate", "valuation", "Terminal growth rate", "rate", D("0"), D("0.06"),
            "Terminal value = final stage-1 cash flow x (1 + g) / (discount rate - g)", "Both valuation models", "terminal-value"),
    Setting("stage1_years", "valuation", "Stage 1 forecast years", "years", D("1"), D("15"),
            "Years of explicit growth before the terminal value", "Both valuation models", "dcf"),
    Setting("fcf_average_years", "valuation", "Years averaged for the base", "years", D("1"), D("5"),
            "Base = average free cash flow (DCF) or dividend per share (DDM) over this many years", "Both valuation models; fundamentals trend", "fcf"),
    Setting("min_margin_of_safety", "tests", "Margin of safety above", "%", D("0"), D("90"),
            "(estimated value - price) / estimated value", "Value test, valuation status, BUY, score wheel", "margin-of-safety"),
    Setting("min_roe", "tests", "Return on equity above", "%", D("0"), D("50"),
            "Net profit / shareholders' equity", "Value test, score wheel", "roe"),
    Setting("max_debt_equity", "tests", "Debt to equity below", "x", D("0.05"), D("5"),
            "Total debt / shareholders' equity", "Value test, score wheel", "debt-to-equity"),
    Setting("min_yield", "tests", "Grossed-up dividend yield above", "%", D("0"), D("20"),
            "Dividend x (1 + franking x 30/70) / price", "Value test, score wheel", "grossed-up-dividend-yield"),
    Setting("earnings_quality_strong", "markers", "Earnings quality: STRONG from", "%", D("50"), D("200"),
            "Operating cash flow / net profit, over the averaging years", "Earnings quality, score wheel", "earnings-quality"),
    Setting("earnings_quality_adequate", "markers", "Earnings quality: ADEQUATE from", "%", D("0"), D("200"),
            "Below this is WEAK, a red flag", "Earnings quality, red flags, AVOID and SELL", "earnings-quality"),
    Setting("new_lows_range", "markers", "New lows: bottom of 52-week range", "%", D("0"), D("50"),
            "Below the 200-day average and at or under this point of the 52-week range", "Price signal, red flags", "price-signal"),
    Setting("dividend_cut_ratio", "markers", "Dividend cut below", "ratio", D("0.5"), D("1"),
            "Latest dividend under this x last year's or the earlier median", "Dividend trend, red flags, SELL", "dividend-trend"),
    Setting("dividend_growth_ratio", "markers", "Dividend growing above", "ratio", D("1"), D("2"),
            "Latest dividend over this x the oldest in the window", "Dividend trend, score wheel", "dividend-trend"),
    Setting("roe_trend_points", "markers", "Fundamentals trend: ROE change", "points", D("0"), D("20"),
            "ROE up or down by more than this many points, latest against oldest report", "Fundamentals trend, value-trap risk", "fundamentals-trend"),
    Setting("revenue_trend_ratio", "markers", "Fundamentals trend: revenue change", "rate", D("0"), D("0.5"),
            "Revenue up or down by more than this, latest against oldest report", "Fundamentals trend, value-trap risk", "fundamentals-trend"),
    Setting("min_mos_trend", "markers", "Momentum: margin of safety up by", "points", D("0"), D("50"),
            "Margin of safety change over 30 days above this", "Momentum, BUY and WATCH reasons, score wheel", "margin-of-safety-trend"),
    Setting("payout_warning", "markers", "Payout ratio red flag above", "%", D("50"), D("1000"),
            "Dividend / earnings per share", "Red flags", "payout-ratio"),
    Setting("overvalued_review", "markers", "Held shares: REVIEW below margin of safety", "%", D("-500"), D("0"),
            "A held share this far above estimated value is flagged for review", "REVIEW", "suggested-action"),
    Setting("score_mos_strong", "score", "Value: margin of safety above (second level)", "%", D("0"), D("95"),
            "Third Value check; the second uses the value test", "Score wheel: Value", "score-wheel"),
    Setting("score_max_pe", "score", "Value: P/E below", "x", D("1"), D("100"),
            "Price / earnings per share, counted only when positive", "Score wheel: Value", "pe"),
    Setting("score_max_pb", "score", "Value: P/B below", "x", D("0.1"), D("20"),
            "Price / book value per share, counted only when positive", "Score wheel: Value", "pb"),
    Setting("score_roe_high", "score", "Performance: ROE above (second level)", "%", D("0"), D("100"),
            "Second ROE check; the first uses the value test", "Score wheel: Performance", "roe"),
    Setting("score_min_roic", "score", "Performance: ROIC above", "%", D("0"), D("100"),
            "Net profit / (debt + equity - cash)", "Score wheel: Performance", "roic"),
    Setting("score_debt_equity_low", "score", "Health: debt to equity below (second level)", "x", D("0"), D("5"),
            "Second debt check; the first uses the value test", "Score wheel: Health", "debt-to-equity"),
    Setting("score_yield_high", "score", "Dividend: grossed-up yield above (second level)", "%", D("0"), D("30"),
            "Second yield check; the first uses the value test", "Score wheel: Dividend", "grossed-up-dividend-yield"),
    Setting("score_max_payout", "score", "Dividend: payout ratio at most", "%", D("10"), D("500"),
            "Dividend / earnings per share", "Score wheel: Dividend", "payout-ratio"),
    Setting("score_upper_range", "score", "Momentum: 52-week range position above", "%", D("0"), D("100"),
            "Where the price sits between its 52-week low (0) and high (100)", "Score wheel: Momentum", "52-week-range"),
)
BY_KEY = {s.key: s for s in SETTINGS}
INTEGER_KEYS = {f.name for f in fields(ModelSettings) if f.type in ("int", int)}


class SettingsError(ValueError):
    """An override that breaks a rule; the message is written for the user."""


def _number(key: str, raw) -> Decimal:
    meta = BY_KEY[key]
    try:
        value = D(str(raw).strip().replace(",", "").rstrip("%"))
    except InvalidOperation:
        raise SettingsError(f"{meta.label}: must be a number") from None
    if not value.is_finite():
        raise SettingsError(f"{meta.label}: must be a number")
    if meta.unit == "rate":
        value = value / 100  # entered as a percent, stored as a fraction
    if not meta.minimum <= value <= meta.maximum:
        scale = 100 if meta.unit == "rate" else 1
        raise SettingsError(f"{meta.label}: must be between {display(meta.minimum * scale)} and {display(meta.maximum * scale)}")
    if key in INTEGER_KEYS:
        if value != value.to_integral_value():
            raise SettingsError(f"{meta.label}: must be a whole number")
        return int(value)
    return value


def display(value) -> str:
    """A number without trailing zeros: 0.80 -> '0.8', 20 -> '20'."""
    text = format(D(str(value)).normalize(), "f")
    return text


def with_overrides(overrides: dict, base: ModelSettings = LIVE) -> ModelSettings:
    """A copy of `base` with each override applied and checked. Rates are
    given as percents (8 for 8%), as the admin console shows them. Unknown
    keys, out-of-range values and inconsistent combinations are refused."""
    changes = {}
    for key, raw in (overrides or {}).items():
        if key not in BY_KEY:
            raise SettingsError(f"Unknown setting: {key}")
        if raw is None or str(raw).strip() == "":
            continue
        changes[key] = _number(key, raw)
    settings = replace(base, **changes)
    check(settings)
    return settings


def check(s: ModelSettings) -> None:
    """Combinations that would break a calculation or a rule's meaning."""
    if s.discount_rate <= s.terminal_growth_rate:
        raise SettingsError("The discount rate must be higher than the terminal growth rate, or the terminal value has no finite answer")
    if s.earnings_quality_strong < s.earnings_quality_adequate:
        raise SettingsError("Earnings quality: STRONG must start at or above ADEQUATE")
    if s.score_mos_strong <= s.min_margin_of_safety:
        raise SettingsError("Score wheel: the second margin-of-safety level must be above the value test's")
    if s.score_roe_high <= s.min_roe:
        raise SettingsError("Score wheel: the second ROE level must be above the value test's")
    if s.score_debt_equity_low >= s.max_debt_equity:
        raise SettingsError("Score wheel: the second debt-to-equity level must be below the value test's")
    if s.score_yield_high <= s.min_yield:
        raise SettingsError("Score wheel: the second yield level must be above the value test's")


def differences(settings: ModelSettings, base: ModelSettings = LIVE) -> dict[str, tuple]:
    """{key: (base value, new value)} for every setting that differs."""
    return {f.name: (getattr(base, f.name), getattr(settings, f.name))
            for f in fields(ModelSettings) if getattr(base, f.name) != getattr(settings, f.name)}


def to_display(key: str, value) -> Decimal | int:
    """The number as the admin console shows it: rates as percents."""
    return value * 100 if BY_KEY[key].unit == "rate" else value
