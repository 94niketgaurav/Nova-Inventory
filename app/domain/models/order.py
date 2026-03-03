# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.domain.enums import OrderStatus


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        # native_enum=False stores values as VARCHAR; SQLAlchemy then coerces
        # the returned string back to an OrderStatus member automatically.
        Enum(OrderStatus, native_enum=False, length=20),
        nullable=False,
        default=OrderStatus.PENDING,
    )
    customer_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    item: Mapped["MenuItem"] = relationship(back_populates="orders")  # noqa: F821
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="order")  # noqa: F821
