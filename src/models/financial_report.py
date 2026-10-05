import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class FinancialReport(Base):
    __tablename__ = "financial_reports"
    __table_args__ = (
        CheckConstraint("period_type IN ('FY', 'H1', 'H2')", name="financial_reports_period_type_check"),
        UniqueConstraint("company_id", "fiscal_year", "period_type"),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE")
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_type: Mapped[str] = mapped_column(String(2), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Income statement & cash flow
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    ebit: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    net_profit_after_tax: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    free_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    capital_expenditure: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    eps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    # Balance sheet
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    total_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    total_equity: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    total_debt: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    cash_and_equivalents: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    net_tangible_assets: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))

    # ASX dividend & franking context
    dividends_per_share: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    abnormal_distributions_per_share: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    reporting_currency: Mapped[str | None] = mapped_column(String(3))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    franking_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=Decimal("100.0"))
    corporate_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), default=Decimal("30.0"))

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    company: Mapped["Company"] = relationship(back_populates="financial_reports")

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"<FinancialReport FY{self.fiscal_year}{self.period_type}>"
