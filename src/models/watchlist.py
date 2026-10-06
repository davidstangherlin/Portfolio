import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Watchlist(Base):
    """A named list of companies to follow - see `watchlists` in db/schema.sql."""

    __tablename__ = "watchlists"

    watchlist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class WatchlistItem(Base):
    """One company on one watchlist, with an optional note and triggers."""

    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watchlists.watchlist_id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.company_id", ondelete="CASCADE"), primary_key=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    mos_above: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    price_below: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    yield_above: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # ETFs and LICs (§26, §27)
    nta_discount_above: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # LICs only (§27)
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
