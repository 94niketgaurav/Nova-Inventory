import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError
from app.domain.models.item import MenuItem
from app.domain.models.stock_movement import StockMovement
from app.repositories.item_repo import ItemRepository
from app.repositories.stock_repo import StockRepository


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self._items = ItemRepository(session)
        self._stock = StockRepository(session)

    async def get_stock(self, item_id: uuid.UUID) -> MenuItem:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)
        return item

    async def get_movements(
        self, item_id: uuid.UUID, limit: int = 100
    ) -> list[StockMovement]:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)
        return await self._stock.list_movements_for_item(item_id, limit)

    async def get_low_stock_items(self) -> list[MenuItem]:
        return await self._items.list_low_stock()
