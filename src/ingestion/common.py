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
    session.add(company)
    session.flush()  # assign company_id without ending the caller's transaction
    return company


def ensure_country(company: Company, client: YahooClient) -> None:
    """Backfill `companies.country` for rows created before the column
    existed. Costs one profile request per company, once - after that the
    stored value is reused. Left NULL (and retried next run) if Yahoo
    doesn't report a country."""
    if company.country is None:
        company.country = client.get_profile().get("country")
