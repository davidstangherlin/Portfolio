import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class ValuationMetric(Base):
    __tablename__ = "valuation_metrics"
    __table_args__ = (UniqueConstraint("company_id", "as_of_date"),)

    valuation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE")
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Classic ratios
    pe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    pb_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_to_fcf: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ev_to_ebit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    roic: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    debt_to_equity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    current_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    # Dividend & gross yield (ASX specific)
    uncapped_dividend_yield: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    grossed_up_dividend_yield: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    # Intrinsic valuations & margin of safety
    dcf_intrinsic_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    graham_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    margin_of_safety_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    company: Mapped["Company"] = relationship(back_populates="valuation_metrics")

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"<ValuationMetric {self.as_of_date} MoS={self.margin_of_safety_percent}>"
