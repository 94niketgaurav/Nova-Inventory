# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OrderStatus
from app.domain.models.order import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def list_orders(
        self,
        status: OrderStatus | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        customer_ref: str | None = None,
    ) -> list[Order]:
        query = select(Order).order_by(Order.created_at.desc())
        if status is not None:
            query = query.where(Order.status == status)
        if from_dt is not None:
            query = query.where(Order.created_at >= from_dt)
        if to_dt is not None:
            query = query.where(Order.created_at <= to_dt)
        if customer_ref is not None:
            query = query.where(Order.customer_ref == customer_ref)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def transition_status(
        self,
        order_id: uuid.UUID,
        expected_version: int,
        new_status: OrderStatus,
    ) -> bool:
        """Optimistic locking: returns False if version mismatch (concurrent update)."""
        result = await self._session.execute(
            update(Order)
            .where(Order.id == order_id, Order.version == expected_version)
            .values(status=new_status, version=Order.version + 1)
            .returning(Order.id)
        )
        return result.scalar_one_or_none() is not None
