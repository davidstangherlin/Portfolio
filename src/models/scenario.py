import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Scenario(Base):
    """A saved what-if: the settings it changes - see `scenarios` in db/schema.sql."""

    __tablename__ = "scenarios"

    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(60), nullable=False)  # unique per owner
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # users.user_id (src/accounts.py)
    notes: Mapped[str | None] = mapped_column(Text)
    overrides: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
