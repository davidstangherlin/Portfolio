import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SignalSnapshot(Base):
    """What Sift said about one company on one valuation date - see the
    `signal_snapshots` table in db/schema.sql. Written once, never edited."""

    __tablename__ = "signal_snapshots"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    action_reason: Mapped[str | None] = mapped_column(Text)
    held: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valuation_status: Mapped[str] = mapped_column(String(12), nullable=False)
    margin_of_safety_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    valuation_method: Mapped[str | None] = mapped_column(String(4))
    graham_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    analyst_target: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))  # Yahoo's mean target that night
    analyst_count: Mapped[int | None] = mapped_column(Integer)
    score_total: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_performance: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_health: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_dividend: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_momentum: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mos_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    roe_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    de_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    yield_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    red_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    rules_version: Mapped[str] = mapped_column(String(10), nullable=False)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
