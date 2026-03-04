# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import MovementType, OrderStatus
from app.domain.models.item import MenuItem
from app.domain.models.order import Order
from app.domain.models.stock_movement import StockMovement
from app.schemas.analytics import MovementAnalytics, OrderAnalytics, StockAnalytics


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_stock_analytics(self) -> StockAnalytics:
        result = await self._session.execute(
            select(
                func.count(MenuItem.id).label("total_items"),
                func.coalesce(func.sum(MenuItem.stock_quantity), 0).label("total_units"),
                func.coalesce(func.sum(MenuItem.price * MenuItem.stock_quantity), 0).label("total_value"),
                func.count(
                    MenuItem.id
                ).filter(
                    MenuItem.stock_quantity <= MenuItem.low_stock_threshold,
                    MenuItem.stock_quantity > 0,
                ).label("low_stock_count"),
                func.count(MenuItem.id).filter(MenuItem.stock_quantity == 0).label("out_of_stock_count"),
            )
        )
        row = result.one()
        return StockAnalytics(
            total_items=row.total_items,
            total_units=row.total_units,
            total_value=Decimal(str(row.total_value)).quantize(Decimal("0.01")),
            low_stock_count=row.low_stock_count,
            out_of_stock_count=row.out_of_stock_count,
        )

    async def get_order_analytics(self, days: int = 30) -> OrderAnalytics:
        since = datetime.now(UTC) - timedelta(days=days)
        result = await self._session.execute(
            select(
                func.count(Order.id).label("total"),
                func.count(Order.id).filter(Order.status == OrderStatus.PENDING).label("pending"),
                func.count(Order.id).filter(Order.status == OrderStatus.CONFIRMED).label("confirmed"),
                func.count(Order.id).filter(Order.status == OrderStatus.SHIPPED).label("shipped"),
                func.count(Order.id).filter(Order.status == OrderStatus.DELIVERED).label("delivered"),
                func.count(Order.id).filter(Order.status == OrderStatus.CANCELLED).label("cancelled"),
                func.count(Order.id).filter(Order.status == OrderStatus.REJECTED).label("rejected"),
            ).where(Order.created_at >= since)
        )
        row = result.one()

        # Revenue: price * quantity for DELIVERED orders
        # Use select_from(Order) so SQLAlchemy knows the left side of the JOIN.
        rev_result = await self._session.execute(
            select(
                func.coalesce(func.sum(MenuItem.price * Order.quantity), 0).label("revenue")
            )
            .select_from(Order)
            .join(MenuItem, Order.item_id == MenuItem.id)
            .where(Order.status == OrderStatus.DELIVERED, Order.created_at >= since)
        )
        revenue = Decimal(str(rev_result.scalar_one())).quantize(Decimal("0.01"))

        # Refund value: price * quantity for CANCELLED orders that had stock deducted
        refund_result = await self._session.execute(
            select(
                func.coalesce(func.sum(MenuItem.price * Order.quantity), 0).label("refund")
            )
            .select_from(Order)
            .join(MenuItem, Order.item_id == MenuItem.id)
            .where(Order.status == OrderStatus.CANCELLED, Order.created_at >= since)
        )
        refund_value = Decimal(str(refund_result.scalar_one())).quantize(Decimal("0.01"))

        return OrderAnalytics(
            total_orders=row.total,
            pending=row.pending,
            confirmed=row.confirmed,
            shipped=row.shipped,
            delivered=row.delivered,
            cancelled=row.cancelled,
            rejected=row.rejected,
            revenue=revenue,
            refund_value=refund_value,
        )

    async def get_movement_analytics(self, days: int = 30) -> MovementAnalytics:
        since = datetime.now(UTC) - timedelta(days=days)
        result = await self._session.execute(
            select(
                func.count(StockMovement.id).filter(
                    StockMovement.movement_type == MovementType.DEDUCTION
                ).label("deductions"),
                func.count(StockMovement.id).filter(
                    StockMovement.movement_type == MovementType.RESTORATION
                ).label("restorations"),
                func.count(StockMovement.id).filter(
                    StockMovement.movement_type == MovementType.ADJUSTMENT
                ).label("adjustments"),
                func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("net_change"),
            ).where(StockMovement.created_at >= since)
        )
        row = result.one()
        return MovementAnalytics(
            total_deductions=row.deductions,
            total_restorations=row.restorations,
            total_adjustments=row.adjustments,
            net_stock_change=row.net_change,
        )
