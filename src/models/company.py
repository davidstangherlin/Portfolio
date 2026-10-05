import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    asx_code: Mapped[str] = mapped_column(String(6), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    country: Mapped[str | None] = mapped_column(String(100))

    daily_prices: Mapped[list["DailyPrice"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    financial_reports: Mapped[list["FinancialReport"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    valuation_metrics: Mapped[list["ValuationMetric"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"<Company {self.asx_code} {self.company_name!r}>"


# NOTE: relationships above reference "DailyPrice" / "FinancialReport" /
# "ValuationMetric" by name rather than importing the classes directly, to
# avoid circular imports. SQLAlchemy resolves those names against its
# mapper registry the first time mappers are configured, so every model
# module must have been imported at least once by then - `src/models/__init__.py`
# does this centrally. Always import models via `src.models`, not this
# module directly, or the string references above will fail to resolve.
