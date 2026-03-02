import uuid
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.domain.enums import MovementType
from app.domain.models.item import MenuItem
from app.domain.models.stock_movement import StockMovement
from app.repositories.item_repo import ItemRepository
from app.repositories.stock_repo import StockRepository

logger = get_logger(__name__)


class ItemService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._items = ItemRepository(session)
        self._stock = StockRepository(session)

    async def create_item(
        self,
        name: str,
        price: Decimal,
        stock_quantity: int,
        description: str | None = None,
        low_stock_threshold: int = 10,
    ) -> MenuItem:
        item = MenuItem(
            name=name,
            description=description,
            price=price,
            stock_quantity=stock_quantity,
            low_stock_threshold=low_stock_threshold,
        )
        item = await self._items.create(item)

        # Audit the initial stock
        await self._stock.create_movement(
            StockMovement(
                item_id=item.id,
                movement_type=MovementType.ADJUSTMENT,
                quantity_delta=stock_quantity,
                stock_before=0,
                stock_after=stock_quantity,
                reason="Initial stock on item creation",
            )
        )
        logger.info("item_created", item_id=str(item.id), name=name, stock=stock_quantity)
        return item

    async def adjust_stock(
        self, item_id: uuid.UUID, delta: int, reason: str
    ) -> MenuItem:
        item = await self._items.get_by_id_with_lock(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)

        stock_before = item.stock_quantity
        new_quantity = stock_before + delta
        if new_quantity < 0:
            from app.core.exceptions import InsufficientStockError
            raise InsufficientStockError(item_id, abs(delta), stock_before)

        item.stock_quantity = new_quantity
        item.version += 1
        await self._stock.create_movement(
            StockMovement(
                item_id=item.id,
                movement_type=MovementType.ADJUSTMENT,
                quantity_delta=delta,
                stock_before=stock_before,
                stock_after=new_quantity,
                reason=reason,
            )
        )
        await self._items.save(item)
        logger.info(
            "stock_adjusted",
            item_id=str(item_id),
            delta=delta,
            stock_before=stock_before,
            stock_after=new_quantity,
        )
        return item

    async def get_item(self, item_id: uuid.UUID) -> MenuItem:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)
        return item

    async def list_items(self) -> list[MenuItem]:
        return await self._items.list_all()

    async def list_low_stock(self) -> list[MenuItem]:
        return await self._items.list_low_stock()
