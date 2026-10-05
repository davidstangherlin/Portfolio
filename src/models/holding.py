import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Holding(Base):
    """One parcel of shares - see the `holdings` table in db/schema.sql."""

    __tablename__ = "holdings"

    holding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"), nullable=False
    )
    asx_code: Mapped[str] = mapped_column(String(6), nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    acquisition_method: Mapped[str] = mapped_column(String(10), nullable=False, default="PURCHASE")
    buy_date: Mapped[date] = mapped_column(Date, nullable=False)
    buy_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    buy_brokerage: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    sell_date: Mapped[date | None] = mapped_column(Date)
    sell_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sell_brokerage: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    broker: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    split_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("holdings.holding_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    @property
    def is_open(self) -> bool:
        return self.sell_date is None

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"<Holding {self.asx_code} {self.units} @ {self.buy_price} on {self.buy_date}>"
