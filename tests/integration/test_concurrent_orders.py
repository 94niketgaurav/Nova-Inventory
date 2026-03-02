"""
Race condition tests — verify SELECT FOR UPDATE prevents oversell
and optimistic locking prevents double-cancel.
"""
import asyncio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = pytest.mark.asyncio


async def test_concurrent_orders_no_oversell(db_engine):
    """
    10 concurrent confirm requests against stock of 5.
    Exactly 5 must succeed; 5 must be rejected/fail.
    Stock must be exactly 0 at the end — never negative.
    """
    STOCK = 5
    NUM_ORDERS = 10

    def make_factory():
        return async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)

    # Create item
    async with make_factory()() as session:
        from app.services.item_service import ItemService
        item = await ItemService(session).create_item(
            "Race Item", price=5.0, stock_quantity=STOCK
        )
        await session.commit()
        item_id = item.id

    # Place 10 pending orders
    order_ids = []
    async with make_factory()() as session:
        from app.services.order_service import OrderService
        svc = OrderService(session)
        for _ in range(NUM_ORDERS):
            order = await svc.place_order(item_id, quantity=1)
            order_ids.append(order.id)
        await session.commit()

    # Confirm all 10 concurrently — this is the race
    async def try_confirm(order_id):
        async with make_factory()() as session:
            from app.services.order_service import OrderService
            svc = OrderService(session)
            try:
                result = await svc.confirm_order(order_id)
                await session.commit()
                return result
            except Exception as exc:
                await session.rollback()
                raise exc

    results = await asyncio.gather(
        *[try_confirm(oid) for oid in order_ids],
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == STOCK, f"Expected {STOCK} successes, got {len(successes)}: {failures}"
    assert len(failures) == NUM_ORDERS - STOCK

    # Final stock must be exactly 0 — never negative
    async with make_factory()() as session:
        from app.repositories.item_repo import ItemRepository
        final = await ItemRepository(session).get_by_id(item_id)
        assert final.stock_quantity == 0, f"Expected 0, got {final.stock_quantity}"
        assert final.stock_quantity >= 0, "Stock went negative — oversell!"


async def test_concurrent_cancellations_no_double_restore(db_engine):
    """
    Two concurrent cancel requests for the same confirmed order.
    Only one must succeed; stock restored exactly once.
    """
    INITIAL_STOCK = 10
    ORDER_QTY = 3

    def make_factory():
        return async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)

    # Setup: create item, place order, confirm it
    async with make_factory()() as session:
        from app.services.item_service import ItemService
        from app.services.order_service import OrderService
        item = await ItemService(session).create_item(
            "Cancel Race Item", price=5.0, stock_quantity=INITIAL_STOCK
        )
        order = await OrderService(session).place_order(item.id, ORDER_QTY)
        await session.commit()
        item_id, order_id = item.id, order.id

    async with make_factory()() as session:
        from app.services.order_service import OrderService
        await OrderService(session).confirm_order(order_id)
        await session.commit()

    # Two concurrent cancel requests
    async def try_cancel(oid):
        async with make_factory()() as session:
            from app.services.order_service import OrderService
            try:
                result = await OrderService(session).cancel_order(oid)
                await session.commit()
                return result
            except Exception as exc:
                await session.rollback()
                raise exc

    results = await asyncio.gather(
        try_cancel(order_id), try_cancel(order_id),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) == 1, "Exactly one cancel should succeed"

    # Stock restored exactly once → back to INITIAL_STOCK - ORDER_QTY (stock after confirm) + ORDER_QTY = INITIAL_STOCK
    async with make_factory()() as session:
        from app.repositories.item_repo import ItemRepository
        final = await ItemRepository(session).get_by_id(item_id)
        assert final.stock_quantity == INITIAL_STOCK
