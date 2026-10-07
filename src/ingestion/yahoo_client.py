"""Thin wrapper around `yfinance` for ASX-listed tickers.

ASX codes are 3-letter codes (e.g. "BHP"); Yahoo Finance addresses them
with a ".AX" suffix ("BHP.AX"). This module only ever talks to Yahoo -
all persistence lives in `src.ingestion.price_ingestion` /
`fundamentals_ingestion`.

`yfinance`'s `.info` / `.financials` / `.balance_sheet` / `.cashflow`
fields are not a stable, versioned API - Yahoo changes field names and
availability without notice, and some fields are simply absent for
smaller ASX-listed companies. Every extraction below is defensive
(`.get(..., None)` / try-except) and returns `None` for anything it
can't find rather than raising, so a partial/missing field never aborts
an entire ingestion run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.currency import cross_rates, invert
from src.ingestion.dividend_history import Payment

logger = logging.getLogger(__name__)


def to_yahoo_symbol(asx_code: str) -> str:
    asx_code = asx_code.strip().upper()
    return asx_code if asx_code.endswith(".AX") else f"{asx_code}.AX"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and (value != value):  # NaN
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass
class PriceBar:
    price_date: date
    close_price: Decimal
    volume: int | None
    market_cap: Decimal | None


@dataclass
class FundamentalsSnapshot:
    fiscal_year: int
    period_type: str  # 'FY' (yfinance only exposes annual statements reliably)
    report_date: date
    revenue: Decimal | None = None
    ebit: Decimal | None = None
    net_profit_after_tax: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    free_cash_flow: Decimal | None = None
    capital_expenditure: Decimal | None = None
    eps: Decimal | None = None
    total_assets: Decimal | None = None
    total_liabilities: Decimal | None = None
    total_equity: Decimal | None = None
    total_debt: Decimal | None = None
    cash_and_equivalents: Decimal | None = None
    net_tangible_assets: Decimal | None = None
    dividends_per_share: Decimal | None = None
    abnormal_distributions_per_share: Decimal | None = None  # excluded one-offs, see dividend_history.py
    reporting_currency: str | None = None  # currency the statements were published in (see currency.py)
    fx_rate: Decimal | None = None  # rate applied to convert them into the trading currency
    franking_percentage: Decimal | None = None  # Yahoo does not expose this - left None
    corporate_tax_rate: Decimal | None = None  # Yahoo does not expose this - left None


class YahooClient:
    def __init__(self, asx_code: str):
        self.asx_code = asx_code.strip().upper()
        self.symbol = to_yahoo_symbol(self.asx_code)
        self._ticker = yf.Ticker(self.symbol)
        # Filled by get_price_history() from the same request: splits and
        # cash distributions in the period fetched, oldest first.
        self.last_splits: list[tuple[date, Decimal]] = []
        self.last_dividends: list[Payment] = []
        # Set when the statements request itself failed (network, Yahoo error),
        # as opposed to Yahoo having no statements: only the former is retried
        # the next night rather than in a week (see due_for_fundamentals).
        self.statements_failed = False

    def get_profile(self) -> dict:
        """Company name / sector / industry / country / currencies / business
        summary, for populating `companies`."""
        try:
            info = self._ticker.get_info()
        except Exception:  # yfinance raises a variety of network/parsing errors
            logger.exception("Failed to fetch profile for %s", self.symbol)
            return {}
        return {
            "company_name": info.get("longName") or info.get("shortName") or self.asx_code,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "trading_currency": info.get("currency"),  # the share price's currency (AUD on the ASX)
            "financial_currency": info.get("financialCurrency"),  # the statements' currency
            "business_summary": (info.get("longBusinessSummary") or "").strip(),
        }

    def get_price_history(self, period: str = "1mo", include_market_cap: bool = True) -> list[PriceBar]:
        """Daily close/volume/market-cap bars for the given yfinance period
        (e.g. '1mo', '6mo', '1y', 'max').

        Closes are the prices actually traded (adjusted for splits only).
        yfinance's default also scales every earlier close down by each
        later dividend, which, refetched a month at a time, left a step in
        the stored history at each ex-date and would count distributions
        twice in a total return (docs/AS_BUILT.md §25). Splits and cash
        distributions in the period are kept in last_splits and
        last_dividends."""
        self.last_splits, self.last_dividends = [], []
        try:
            history = self._ticker.history(period=period, interval="1d", auto_adjust=False, actions=True)
        except Exception:
            logger.exception("Failed to fetch price history for %s", self.symbol)
            return []

        if history is None or history.empty:
            return []

        for column, target in (("Stock Splits", self.last_splits), ("Dividends", self.last_dividends)):
            if column not in history:
                continue
            for idx, value in history[column].items():
                amount = _to_decimal(float(value)) if pd.notna(value) else None
                if amount:
                    day = idx.date() if hasattr(idx, "date") else idx
                    target.append((day, amount) if column == "Stock Splits" else Payment(ex_date=day, amount=amount))

        shares_outstanding = None
        if include_market_cap:
            try:
                shares_outstanding = self._ticker.get_info().get("sharesOutstanding")
            except Exception:
                logger.debug("sharesOutstanding unavailable for %s", self.symbol, exc_info=True)

        bars: list[PriceBar] = []
        for idx, row in history.iterrows():
            close = _to_decimal(row.get("Close"))
            if close is None:
                continue
            volume = int(row["Volume"]) if pd.notna(row.get("Volume")) else None
            market_cap = close * Decimal(str(shares_outstanding)) if shares_outstanding else None
            price_date = idx.date() if hasattr(idx, "date") else idx
            bars.append(PriceBar(price_date=price_date, close_price=close, volume=volume, market_cap=market_cap))
        return bars

    def get_annual_fundamentals(self, max_years: int = 4) -> list[FundamentalsSnapshot]:
        """Best-effort annual financial-report snapshots from Yahoo's income
        statement / balance sheet / cash flow statement."""
        try:
            income_stmt = self._ticker.get_income_stmt(freq="yearly")
            balance_sheet = self._ticker.get_balance_sheet(freq="yearly")
            cash_flow = self._ticker.get_cash_flow(freq="yearly")
        except Exception:
            logger.exception("Failed to fetch financial statements for %s", self.symbol)
            self.statements_failed = True
            return []

        if income_stmt is None or income_stmt.empty:
            return []

        snapshots: list[FundamentalsSnapshot] = []
        for period_end in list(income_stmt.columns)[:max_years]:
            report_date = period_end.date() if hasattr(period_end, "date") else period_end

            def inc(row: str) -> Decimal | None:
                return _to_decimal(income_stmt.loc[row, period_end]) if row in income_stmt.index else None

            def bal(row: str) -> Decimal | None:
                if balance_sheet is None or period_end not in balance_sheet.columns or row not in balance_sheet.index:
                    return None
                return _to_decimal(balance_sheet.loc[row, period_end])

            def cf(row: str) -> Decimal | None:
                if cash_flow is None or period_end not in cash_flow.columns or row not in cash_flow.index:
                    return None
                return _to_decimal(cash_flow.loc[row, period_end])

            # NOTE: yfinance 1.7.x returns PascalCase, no-space row labels
            # (e.g. "NetIncome", "StockholdersEquity") - NOT the spaced,
            # title-cased form ("Net Income", "Stockholders Equity") used
            # in earlier yfinance releases and in this module's first cut.
            # Confirmed directly against a live pull (2026-10-01); see
            # docs/AS_BUILT.md §11 for the history of this mismatch.
            operating_cf = cf("OperatingCashFlow") or cf("CashFlowFromContinuingOperatingActivities")
            capex = cf("CapitalExpenditure")
            free_cf = cf("FreeCashFlow")
            if free_cf is None and operating_cf is not None and capex is not None:
                # Yahoo reports capex as a negative outflow already.
                free_cf = operating_cf + capex

            total_debt = bal("TotalDebt")
            if total_debt is None:
                long_term = bal("LongTermDebt") or Decimal("0")
                short_term = bal("CurrentDebt") or Decimal("0")
                total_debt = long_term + short_term if (long_term or short_term) else None

            snapshots.append(
                FundamentalsSnapshot(
                    fiscal_year=report_date.year,
                    period_type="FY",
                    report_date=report_date,
                    revenue=inc("TotalRevenue"),
                    ebit=inc("EBIT"),
                    net_profit_after_tax=inc("NetIncome"),
                    operating_cash_flow=operating_cf,
                    free_cash_flow=free_cf,
                    capital_expenditure=capex,
                    eps=inc("DilutedEPS") or inc("BasicEPS"),
                    total_assets=bal("TotalAssets"),
                    total_liabilities=bal("TotalLiabilitiesNetMinorityInterest"),
                    total_equity=bal("StockholdersEquity") or bal("CommonStockEquity"),
                    total_debt=total_debt,
                    cash_and_equivalents=bal("CashAndCashEquivalents"),
                    net_tangible_assets=bal("TangibleBookValue"),
                    dividends_per_share=None,  # sourced separately via get_dividend_payments
                )
            )
        return snapshots

    @staticmethod
    def _fx_closes(pair: str, start: date, end: date) -> list[tuple[date, Decimal]]:
        """Daily closes for one Yahoo currency symbol, or [] if Yahoo has
        none. yfinance's own "possibly delisted" errors are silenced while
        probing, since a missing symbol is expected and handled."""
        yf_logger = logging.getLogger("yfinance")
        level = yf_logger.level
        yf_logger.setLevel(logging.CRITICAL)
        try:
            history = yf.Ticker(pair).history(start=start, end=end, interval="1d", auto_adjust=False)
        except Exception:
            logger.warning("No exchange rates from Yahoo for %s", pair)
            return []
        finally:
            yf_logger.setLevel(level)
        if history is None or history.empty or "Close" not in history.columns:
            return []
        out = []
        for ts, value in history["Close"].items():
            rate = _to_decimal(float(value))
            if rate is not None and rate > 0:
                out.append((ts.date() if hasattr(ts, "date") else ts, rate))
        return out

    @classmethod
    def get_fx_history(cls, from_currency: str, to_currency: str, start: date, end: date) -> list[tuple[date, Decimal]]:
        """Daily closing exchange rates (to_currency per from_currency), e.g.
        USD->AUD from Yahoo's USDAUD=X. When Yahoo has no direct pair (the
        Papua New Guinea kina: no PGKAUD=X), the rate is chained through the
        US dollar, trying each way Yahoo quotes it (PGKUSD=X, USDPGK=X,
        PGK=X, which is USD->PGK). Empty if no route works; the caller
        decides what an unavailable rate means."""
        direct = cls._fx_closes(f"{from_currency}{to_currency}=X", start, end)
        if direct or "USD" in (from_currency, to_currency):
            return direct

        def leg(base: str, quote: str) -> list[tuple[date, Decimal]]:
            """base->quote where one side is USD; Yahoo's bare "XXX=X" is USD->XXX."""
            other = quote if base == "USD" else base
            closes = cls._fx_closes(f"{base}{quote}=X", start, end)
            if not closes:
                closes = invert(cls._fx_closes(f"{quote}{base}=X", start, end))
            if not closes:
                bare = cls._fx_closes(f"{other}=X", start, end)
                closes = bare if base == "USD" else invert(bare)
            return closes

        to_usd = leg(from_currency, "USD")
        from_usd = leg("USD", to_currency) if to_usd else []
        rates = cross_rates(to_usd, from_usd)
        if rates:
            logger.info("%s/%s rates chained through USD (%d days)", from_currency, to_currency, len(rates))
        return rates

    def get_dividend_payments(self) -> list[Payment]:
        """Every per-share dividend Yahoo has recorded, oldest first. Raw:
        abnormal one-offs and financial-year matching are handled by
        src.ingestion.dividend_history."""
        try:
            dividends = self._ticker.dividends
        except Exception:
            logger.exception("Failed to fetch dividends for %s", self.symbol)
            return []
        if dividends is None or dividends.empty:
            return []
        payments = []
        for ts, amount in dividends.items():
            value = _to_decimal(float(amount))
            if value is not None:
                payments.append(Payment(ex_date=ts.date() if hasattr(ts, "date") else ts, amount=value))
        return sorted(payments, key=lambda p: p.ex_date)

    def get_insights(self, today: date) -> Insights | None:
        """Analyst ratings and price targets, and the major, mutual fund and
        institutional holders (docs/AS_BUILT.md §29). Three Yahoo requests:
        the profile (consensus and targets), the monthly rating counts, and
        the holders. None if the profile can't be fetched at all, so the
        company is tried again next run; a missing part is just left empty."""
        try:
            info = self._ticker.get_info()
        except Exception:
            logger.exception("Failed to fetch analyst data for %s", self.symbol)
            return None

        def part(name, fetch):
            try:
                return fetch()
            except Exception:  # yfinance raises when Yahoo has nothing for a small company
                logger.warning("No %s from Yahoo for %s", name, self.symbol)
                return None

        trend = part("analyst ratings", self._ticker.get_recommendations)
        major = part("major holders", self._ticker.get_major_holders)
        funds = part("mutual fund holders", self._ticker.get_mutualfund_holders)
        institutions = part("institutional holders", self._ticker.get_institutional_holders)
        return parse_insights(info, trend, major, funds, institutions, today)

    def _fund_data(self, symbol: str | None = None) -> FundProfile | None:
        """Yahoo's fund data for this fund (or any Yahoo `symbol`), or None
        if Yahoo has none (an LIC, which Yahoo lists as a company) or the
        request fails. yfinance's "no fund data" error is expected and silenced."""
        yf_logger = logging.getLogger("yfinance")
        level = yf_logger.level
        yf_logger.setLevel(logging.CRITICAL)
        try:
            fd = (yf.Ticker(symbol) if symbol else self._ticker).get_funds_data()
            description = fd.description
            return parse_fund_profile(description, fd.asset_classes, fd.top_holdings, fd.sector_weightings,
                                      fd.bond_ratings, fd.bond_holdings)
        except Exception:
            return None
        finally:
            yf_logger.setLevel(level)

    def get_fund_profile(self) -> FundProfile | None:
        """Description, asset mix, top 10 holdings, sector weightings and bond
        details from Yahoo's fund data (one request). A feeder fund that puts
        nearly everything into one other fund (the ASX's IVV holds the US
        IVV) is looked through: the underlying fund's top 10 and sectors are
        used, scaled by how much of the feeder it is (see look_through()).
        Yahoo lists LICs as companies, with no fund data: they get the
        description from the company profile instead. None if neither
        request works, so the fund is tried again next run."""
        profile = self._fund_data()
        if profile is not None:
            return look_through(profile, self._fund_data, self.symbol)
        try:
            info = self._ticker.get_info()
        except Exception:
            logger.warning("No fund or company profile from Yahoo for %s", self.symbol)
            return None
        return FundProfile(description=(info.get("longBusinessSummary") or "").strip() or None, holdings=[])

# ---------- analyst and holder insights (docs/AS_BUILT.md §29) ----------

TOP_HOLDERS = 10


@dataclass
class RatingMonth:
    rating_month: date
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int


@dataclass
class Holder:
    rank: int
    holder: str
    shares: Decimal | None
    percent_held: Decimal | None
    value: Decimal | None
    percent_change: Decimal | None
    date_reported: date | None


@dataclass
class Insights:
    recommendation_key: str | None = None
    recommendation_mean: Decimal | None = None
    analyst_count: int | None = None
    target_low: Decimal | None = None
    target_mean: Decimal | None = None
    target_median: Decimal | None = None
    target_high: Decimal | None = None
    insiders_percent: Decimal | None = None
    institutions_percent: Decimal | None = None
    institutions_float_percent: Decimal | None = None
    institutions_count: int | None = None
    ratings: list[RatingMonth] | None = None
    funds: list[Holder] | None = None
    institutions: list[Holder] | None = None


def _percent(value: Any) -> Decimal | None:
    """Yahoo's fractions (0.125) as percents (12.5000)."""
    d = _to_decimal(value)
    return (d * 100).quantize(Decimal("0.0001")) if d is not None else None


def _int(value: Any) -> int | None:
    d = _to_decimal(value)
    return int(d) if d is not None else None


def _month_offset(today: date, period: str) -> date | None:
    """Yahoo's '0m', '-1m', ... as the first day of that month."""
    try:
        back = -int(str(period).strip().rstrip("m"))
    except ValueError:
        return None
    months = today.year * 12 + today.month - 1 - back
    return date(months // 12, months % 12 + 1, 1)


def _empty(frame) -> bool:
    return frame is None or not isinstance(frame, pd.DataFrame) or frame.empty


def parse_ratings(trend, today: date) -> list[RatingMonth]:
    """Monthly buy / hold / sell counts, oldest month first. Months with no
    analysts at all are left out."""
    if _empty(trend):
        return []
    out = []
    for row in trend.to_dict("records"):
        month = _month_offset(today, row.get("period", ""))
        counts = [_int(row.get(k)) or 0 for k in ("strongBuy", "buy", "hold", "sell", "strongSell")]
        if month is not None and sum(counts) > 0:
            out.append(RatingMonth(month, *counts))
    return sorted(out, key=lambda r: r.rating_month)


def parse_holders(frame) -> list[Holder]:
    """The top holders as Yahoo lists them (largest first)."""
    if _empty(frame):
        return []
    out = []
    for row in frame.head(TOP_HOLDERS).to_dict("records"):
        name = str(row.get("Holder") or "").strip()
        if not name:
            continue
        reported = row.get("Date Reported")
        reported = reported.date() if hasattr(reported, "date") and not pd.isna(reported) else None
        shares = _to_decimal(row.get("Shares"))
        out.append(Holder(len(out) + 1, name[:255], shares.quantize(Decimal("1")) if shares is not None else None,
                          _percent(row.get("pctHeld")), _to_decimal(row.get("Value")),
                          _percent(row.get("pctChange")), reported))
    return out


def parse_major_holders(frame) -> dict:
    """The ownership breakdown, keyed by Yahoo's names."""
    if _empty(frame) or "Value" not in frame.columns:
        return {}
    return {str(k): v for k, v in frame["Value"].items()}


def parse_insights(info: dict | None, trend, major, funds, institutions, today: date) -> Insights:
    info = info or {}
    breakdown = parse_major_holders(major)
    key = info.get("recommendationKey")
    return Insights(
        recommendation_key=key if key and key != "none" else None,
        recommendation_mean=_to_decimal(info.get("recommendationMean")),
        analyst_count=_int(info.get("numberOfAnalystOpinions")),
        target_low=_to_decimal(info.get("targetLowPrice")),
        target_mean=_to_decimal(info.get("targetMeanPrice")),
        target_median=_to_decimal(info.get("targetMedianPrice")),
        target_high=_to_decimal(info.get("targetHighPrice")),
        insiders_percent=_percent(breakdown.get("insidersPercentHeld", info.get("heldPercentInsiders"))),
        institutions_percent=_percent(breakdown.get("institutionsPercentHeld", info.get("heldPercentInstitutions"))),
        institutions_float_percent=_percent(breakdown.get("institutionsFloatPercentHeld")),
        institutions_count=_int(breakdown.get("institutionsCount")),
        ratings=parse_ratings(trend, today),
        funds=parse_holders(funds),
        institutions=parse_holders(institutions),
    )


# ---------- fund profiles: description, holdings, sectors (docs/AS_BUILT.md §26.3) ----------

@dataclass
class FundHolding:
    rank: int
    symbol: str | None
    name: str
    weight_percent: Decimal | None


@dataclass
class FundProfile:
    description: str | None = None
    stock_percent: Decimal | None = None
    bond_percent: Decimal | None = None
    cash_percent: Decimal | None = None
    other_percent: Decimal | None = None
    sector_weightings: dict[str, float] | None = None  # percents, largest first
    bond_ratings: dict[str, float] | None = None       # percents
    duration_years: Decimal | None = None
    maturity_years: Decimal | None = None
    holdings: list[FundHolding] | None = None
    # Set when the holdings and sectors are another fund's, looked through
    # (a feeder fund): that fund's Yahoo symbol, name and share of this one.
    look_through_symbol: str | None = None
    look_through_name: str | None = None
    look_through_percent: Decimal | None = None

    @property
    def top10_percent(self) -> Decimal | None:
        weights = [h.weight_percent for h in self.holdings or [] if h.weight_percent is not None]
        return sum(weights, Decimal("0")).quantize(Decimal("0.01")) if weights else None


def _percents(values: dict | None) -> dict[str, float]:
    """Yahoo's {key: fraction} as {key: percent}, zeros dropped, largest
    first. Already-percent figures (summing well over 1) are left as they are."""
    clean = {str(k): float(v) for k, v in (values or {}).items() if _to_decimal(v) is not None and float(v) > 0}
    scale = 1 if sum(clean.values()) > 1.5 else 100
    return dict(sorted(((k, round(v * scale, 2)) for k, v in clean.items()), key=lambda kv: -kv[1]))


def _frame_value(frame, row: str):
    if _empty(frame) or row not in frame.index:
        return None
    return _to_decimal(frame.loc[row].iloc[0])


def parse_fund_profile(description: str | None, asset_classes: dict | None, top_holdings, sector_weightings: dict | None,
                       bond_ratings: dict | None, bond_holdings) -> FundProfile:
    """Yahoo's fund data (yfinance FundsData) as a FundProfile."""
    assets = _percents(asset_classes)
    other = sum(assets.get(k, 0) for k in ("preferredPosition", "convertiblePosition", "otherPosition"))
    holdings = []
    if not _empty(top_holdings):
        for symbol, row in top_holdings.head(10).iterrows():
            name = str(row.get("Name") or symbol or "").strip()
            if not name:
                continue
            weight = _to_decimal(row.get("Holding Percent"))
            holdings.append(FundHolding(len(holdings) + 1, str(symbol).strip() or None, name[:255],
                                        (weight * 100).quantize(Decimal("0.01")) if weight is not None else None))
    pct = lambda k: Decimal(str(assets[k])).quantize(Decimal("0.01")) if k in assets else None  # noqa: E731
    return FundProfile(
        description=(description or "").strip() or None,
        stock_percent=pct("stockPosition"), bond_percent=pct("bondPosition"), cash_percent=pct("cashPosition"),
        other_percent=Decimal(str(other)).quantize(Decimal("0.01")) if other else None,
        sector_weightings=_percents(sector_weightings) or None,
        bond_ratings=_percents(bond_ratings) or None,
        duration_years=_frame_value(bond_holdings, "Duration"),
        maturity_years=_frame_value(bond_holdings, "Maturity"),
        holdings=holdings,
    )


LOOK_THROUGH_PERCENT = Decimal("80")  # one holding this big makes the fund a feeder into it


def look_through(profile: FundProfile, fetch, own_symbol: str | None = None) -> FundProfile:
    """For a feeder fund (one holding of LOOK_THROUGH_PERCENT or more, with a
    Yahoo symbol), replace its holdings with the underlying fund's top 10,
    each scaled by the feeder's share in it, and fill sectors, bond ratings,
    duration and maturity from it where the feeder has none. `fetch(symbol)`
    returns the underlying FundProfile or None; one level only. The
    feeder's own description and asset mix are kept."""
    top = (profile.holdings or [None])[0]
    if top is None or not top.symbol or top.weight_percent is None or top.weight_percent < LOOK_THROUGH_PERCENT \
            or top.symbol.upper() == (own_symbol or "").upper():
        return profile
    inner = fetch(top.symbol)
    if inner is None or not (inner.holdings or inner.sector_weightings):
        return profile
    share = top.weight_percent / 100
    profile.holdings = [FundHolding(h.rank, h.symbol, h.name,
                                    (h.weight_percent * share).quantize(Decimal("0.01")) if h.weight_percent is not None else None)
                        for h in inner.holdings or []]
    profile.sector_weightings = profile.sector_weightings or inner.sector_weightings
    profile.bond_ratings = profile.bond_ratings or inner.bond_ratings
    profile.duration_years = profile.duration_years if profile.duration_years is not None else inner.duration_years
    profile.maturity_years = profile.maturity_years if profile.maturity_years is not None else inner.maturity_years
    profile.look_through_symbol, profile.look_through_name, profile.look_through_percent = top.symbol, top.name, top.weight_percent
    return profile
