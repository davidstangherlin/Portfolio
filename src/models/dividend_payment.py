import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class DividendPayment(Base):
    """One per-share dividend as Yahoo records it, by ex-dividend date, in
    the trading currency. `abnormal` marks a one-off held out of every
    dividend figure (src/ingestion/dividend_history.py). Used to mark
    dividends on the web GUI's price chart."""

    __tablename__ = "dividend_payments"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE"), primary_key=True
    )
    ex_date: Mapped[date] = mapped_column(Date, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    abnormal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
