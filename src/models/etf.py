import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base

_PCT = Numeric(10, 2)
_MONEY = Numeric(18, 2)


class EtfMonthly(Base):
    """One ETF's row in one month's ASX Investment Products report - see
    `etf_monthly` in db/schema.sql."""

    __tablename__ = "etf_monthly"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE"), primary_key=True)
    report_month: Mapped[date] = mapped_column(Date, primary_key=True)
    fund_name: Mapped[str | None] = mapped_column(String(255))
    issuer: Mapped[str | None] = mapped_column(String(120))
    product_type: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(120))
    sub_category: Mapped[str | None] = mapped_column(String(120))
    benchmark: Mapped[str | None] = mapped_column(String(255))
    mer_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    fum_aud: Mapped[Decimal | None] = mapped_column(_MONEY)
    net_flows_aud: Mapped[Decimal | None] = mapped_column(_MONEY)
    avg_spread_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    value_traded_aud: Mapped[Decimal | None] = mapped_column(_MONEY)
    distribution_yield: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    distribution_frequency: Mapped[str | None] = mapped_column(String(40))
    listing_date: Mapped[date | None] = mapped_column(Date)
    return_1m: Mapped[Decimal | None] = mapped_column(_PCT)
    return_3m: Mapped[Decimal | None] = mapped_column(_PCT)
    return_6m: Mapped[Decimal | None] = mapped_column(_PCT)
    return_1y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_3y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_5y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_10y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_since_inception: Mapped[Decimal | None] = mapped_column(_PCT)
    nta_pre_tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))      # LICs (§27)
    nta_date: Mapped[date | None] = mapped_column(Date)
    nta_premium_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    performance_fee: Mapped[str | None] = mapped_column(String(10))
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_file: Mapped[str | None] = mapped_column(String(255))
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())


class EtfPerformance(Base):
    """Sift's own performance figures for one ETF - see `etf_performance`
    in db/schema.sql and src/etf/performance.py."""

    __tablename__ = "etf_performance"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE"), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    first_price_date: Mapped[date | None] = mapped_column(Date)
    return_1m: Mapped[Decimal | None] = mapped_column(_PCT)
    return_3m: Mapped[Decimal | None] = mapped_column(_PCT)
    return_6m: Mapped[Decimal | None] = mapped_column(_PCT)
    return_1y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_3y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_5y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_10y: Mapped[Decimal | None] = mapped_column(_PCT)
    return_since_inception: Mapped[Decimal | None] = mapped_column(_PCT)
    distributions_12m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    distribution_yield_12m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    check_month: Mapped[date | None] = mapped_column(Date)
    check_return_1y: Mapped[Decimal | None] = mapped_column(_PCT)
    reported_return_1y: Mapped[Decimal | None] = mapped_column(_PCT)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), onupdate=func.current_timestamp())
