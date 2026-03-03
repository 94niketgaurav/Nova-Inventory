# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class MenuItem(Base, TimestampMixin):
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_menu_items_stock_non_negative"),
        CheckConstraint("price > 0", name="ck_menu_items_price_positive"),
        CheckConstraint("low_stock_threshold >= 0", name="ck_menu_items_threshold_non_negative"),
        UniqueConstraint("name", name="uq_menu_items_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    orders: Mapped[list["Order"]] = relationship(back_populates="item")  # noqa: F821
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="item")  # noqa: F821

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("stock_quantity", 0)
        kwargs.setdefault("low_stock_threshold", 10)
        kwargs.setdefault("version", 1)
        super().__init__(**kwargs)

    @property
    def is_low_stock(self) -> bool:
        return self.stock_quantity <= self.low_stock_threshold
