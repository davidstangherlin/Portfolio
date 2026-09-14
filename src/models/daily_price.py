import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("company_id", "price_date"),)

    price_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE")
    )
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    company: Mapped["Company"] = relationship(back_populates="daily_prices")

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"<DailyPrice {self.price_date} close={self.close_price}>"
