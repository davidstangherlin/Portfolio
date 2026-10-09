import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Portfolio(Base):
    """A named group of parcels owned by one taxpayer - see the
    `portfolios` table in db/schema.sql. `tax_type` sets the CGT discount
    (src/portfolio/cgt.py DISCOUNT_RATES)."""

    __tablename__ = "portfolios"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(60), nullable=False)  # unique per owner
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # users.user_id (src/accounts.py)
    tax_type: Mapped[str] = mapped_column(String(10), nullable=False, default="INDIVIDUAL")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"<Portfolio {self.name} ({self.tax_type})>"
