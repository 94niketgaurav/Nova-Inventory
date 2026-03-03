# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.item import MenuItem


class ItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: MenuItem) -> MenuItem:
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> MenuItem | None:
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_lock(self, item_id: uuid.UUID) -> MenuItem | None:
        """Acquires a row-level exclusive lock. Use inside a transaction."""
        result = await self._session.execute(
            select(MenuItem).where(MenuItem.id == item_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[MenuItem]:
        result = await self._session.execute(select(MenuItem).order_by(MenuItem.name))
        return list(result.scalars().all())

    async def list_low_stock(self) -> list[MenuItem]:
        result = await self._session.execute(
            select(MenuItem).where(
                MenuItem.stock_quantity <= MenuItem.low_stock_threshold
            ).order_by(MenuItem.stock_quantity)
        )
        return list(result.scalars().all())

    async def save(self, item: MenuItem) -> MenuItem:
        await self._session.flush()
        await self._session.refresh(item)
        return item
