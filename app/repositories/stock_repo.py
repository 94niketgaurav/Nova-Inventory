import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.models.stock_movement import StockMovement


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_movement(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        await self._session.flush()
        return movement

    async def list_movements_for_item(
        self, item_id: uuid.UUID, limit: int = 100
    ) -> list[StockMovement]:
        result = await self._session.execute(
            select(StockMovement)
            .where(StockMovement.item_id == item_id)
            .order_by(StockMovement.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
