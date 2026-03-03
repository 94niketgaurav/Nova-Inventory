# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheService, get_redis
from app.core.exceptions import (
    ConflictError,
    InsufficientStockError,
    InvalidTransitionError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.domain.enums import MovementType, OrderStatus
from app.domain.models.order import Order
from app.domain.models.stock_movement import StockMovement
from app.repositories.item_repo import ItemRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.stock_repo import StockRepository

logger = get_logger(__name__)


class OrderService:
    def __init__(
        self,
        session: AsyncSession,
        cache: CacheService | None = None,
    ) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._items = ItemRepository(session)
        self._stock = StockRepository(session)
        self._cache = cache if cache is not None else CacheService(get_redis())

    async def place_order(
        self, item_id: uuid.UUID, quantity: int, customer_ref: str | None = None
    ) -> Order:
        item = await self._items.get_by_id(item_id)
        if not item:
            raise NotFoundError("MenuItem", item_id)

        order = Order(
            item_id=item_id,
            quantity=quantity,
            status=OrderStatus.PENDING,
            customer_ref=customer_ref,
        )
        order = await self._orders.create(order)
        logger.info("order_placed", order_id=str(order.id), item_id=str(item_id), qty=quantity)
        return order

    async def confirm_order(self, order_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        if not order.status.can_transition_to(OrderStatus.CONFIRMED):
            raise InvalidTransitionError(order.status, OrderStatus.CONFIRMED)

        # Pessimistic lock on the item row — prevents concurrent oversell
        item = await self._items.get_by_id_with_lock(order.item_id)
        if not item:
            raise NotFoundError("MenuItem", order.item_id)

        if item.stock_quantity < order.quantity:
            # Reject the order — insufficient stock
            updated = await self._orders.transition_status(
                order_id, order.version, OrderStatus.REJECTED
            )
            if not updated:
                raise ConflictError("Order", order_id)
            logger.warning(
                "order_rejected_insufficient_stock",
                order_id=str(order_id),
                available=item.stock_quantity,
                requested=order.quantity,
            )
            raise InsufficientStockError(item.id, order.quantity, item.stock_quantity)

        # Deduct stock atomically within this locked transaction
        stock_before = item.stock_quantity
        item.stock_quantity -= order.quantity
        item.version += 1

        await self._stock.create_movement(
            StockMovement(
                item_id=item.id,
                order_id=order.id,
                movement_type=MovementType.DEDUCTION,
                quantity_delta=-order.quantity,
                stock_before=stock_before,
                stock_after=item.stock_quantity,
                reason=f"Stock deducted for order {order_id}",
            )
        )
        await self._items.save(item)
        # Write-through: sync cache immediately after stock deduction
        await self._cache.set_stock(item.id, item.stock_quantity)

        updated = await self._orders.transition_status(
            order_id, order.version, OrderStatus.CONFIRMED
        )
        if not updated:
            raise ConflictError("Order", order_id)

        logger.info(
            "order_confirmed",
            order_id=str(order_id),
            stock_before=stock_before,
            stock_after=item.stock_quantity,
        )
        return await self._orders.get_by_id(order_id)

    async def ship_order(self, order_id: uuid.UUID) -> Order:
        return await self._transition(order_id, OrderStatus.SHIPPED)

    async def deliver_order(self, order_id: uuid.UUID) -> Order:
        return await self._transition(order_id, OrderStatus.DELIVERED)

    async def cancel_order(self, order_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        if not order.status.can_transition_to(OrderStatus.CANCELLED):
            raise InvalidTransitionError(order.status, OrderStatus.CANCELLED)

        should_restore = order.status in OrderStatus.stock_holding_states()

        if should_restore:
            item = await self._items.get_by_id_with_lock(order.item_id)
            if item:
                stock_before = item.stock_quantity
                item.stock_quantity += order.quantity
                item.version += 1
                await self._stock.create_movement(
                    StockMovement(
                        item_id=item.id,
                        order_id=order.id,
                        movement_type=MovementType.RESTORATION,
                        quantity_delta=order.quantity,
                        stock_before=stock_before,
                        stock_after=item.stock_quantity,
                        reason=f"Stock restored on cancellation of order {order_id}",
                    )
                )
                await self._items.save(item)
                # Write-through: sync cache after stock restoration
                await self._cache.set_stock(item.id, item.stock_quantity)
                logger.info(
                    "stock_restored",
                    order_id=str(order_id),
                    qty=order.quantity,
                    stock_after=item.stock_quantity,
                )

        updated = await self._orders.transition_status(
            order_id, order.version, OrderStatus.CANCELLED
        )
        if not updated:
            raise ConflictError("Order", order_id)

        return await self._orders.get_by_id(order_id)

    async def get_order(self, order_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        return order

    async def _transition(self, order_id: uuid.UUID, new_status: OrderStatus) -> Order:
        order = await self._orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order", order_id)
        if not order.status.can_transition_to(new_status):
            raise InvalidTransitionError(order.status, new_status)
        updated = await self._orders.transition_status(order_id, order.version, new_status)
        if not updated:
            raise ConflictError("Order", order_id)
        logger.info("order_transitioned", order_id=str(order_id), new_status=new_status)
        return await self._orders.get_by_id(order_id)
