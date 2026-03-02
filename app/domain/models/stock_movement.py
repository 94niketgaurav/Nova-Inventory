import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.domain.enums import MovementType


class StockMovement(Base):
    """Append-only audit log. Never UPDATE or DELETE rows."""
    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )
    movement_type: Mapped[MovementType] = mapped_column(Text, nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    item: Mapped["MenuItem"] = relationship(back_populates="stock_movements")
    order: Mapped["Order | None"] = relationship(back_populates="stock_movements")
