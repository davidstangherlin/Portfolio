from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ingestion.yahoo_client import YahooClient, to_yahoo_symbol
from src.models import Company


def get_or_create_company(session: Session, asx_code: str, client: YahooClient | None = None) -> Company:
    """Fetch the Company row for `asx_code`, creating it (populated from
    Yahoo's profile data) if it doesn't exist yet."""
    asx_code = asx_code.strip().upper()
    company = session.execute(select(Company).where(Company.asx_code == asx_code)).scalar_one_or_none()
    if company is not None:
        return company

    client = client or YahooClient(asx_code)
    profile = client.get_profile()

    company = Company(
        ticker=to_yahoo_symbol(asx_code),
        asx_code=asx_code,
        company_name=profile.get("company_name") or asx_code,
        sector=profile.get("sector"),
        industry=profile.get("industry"),
        country=profile.get("country"),
    )
    _fill_currencies(company, profile)
    session.add(company)
    session.flush()  # assign company_id without ending the caller's transaction
    return company


def _fill_currencies(company: Company, profile: dict) -> None:
    """A fetched profile without a statements currency means statements
    in the trading currency; ASX listings trade in AUD unless Yahoo says
    otherwise. An empty profile (fetch failed) leaves both unset so the
    next run retries."""
    if not profile:
        return
    if company.trading_currency is None:
        company.trading_currency = profile.get("trading_currency") or "AUD"
    if company.financial_currency is None:
        company.financial_currency = profile.get("financial_currency") or company.trading_currency


def ensure_profile(company: Company, client: YahooClient) -> None:
    """Backfill `country` and the two currency columns for companies
    created before those columns existed. One profile request per company,
    once; after that the stored values are reused."""
    if company.country is not None and company.financial_currency is not None and company.trading_currency is not None:
        return
    profile = client.get_profile()
    if company.country is None:
        company.country = profile.get("country")
    _fill_currencies(company, profile)
