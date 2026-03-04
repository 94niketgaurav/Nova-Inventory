# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_item(client: AsyncClient, stock: int = 20, name: str | None = None) -> dict:
    resp = await client.post("/api/v1/items", json={
        "name": name or f"Test Item {id(client)}-{stock}",
        "price": "9.99",
        "stock_quantity": stock,
        "low_stock_threshold": 5,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _place_order(client: AsyncClient, item_id: str, qty: int = 2) -> dict:
    resp = await client.post("/api/v1/orders", json={
        "item_id": item_id,
        "quantity": qty,
        "customer_ref": "test-customer",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_full_happy_path(client: AsyncClient):
    """PENDING → CONFIRMED → SHIPPED → DELIVERED"""
    item = await _create_item(client, stock=10, name="Happy Path Item")
    order = await _place_order(client, item["id"], qty=3)
    assert order["status"] == "PENDING"

    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CONFIRMED"

    # Stock was deducted
    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 7  # 10 - 3

    r = await client.post(f"/api/v1/orders/{order['id']}/ship")
    assert r.status_code == 200
    assert r.json()["status"] == "SHIPPED"

    r = await client.post(f"/api/v1/orders/{order['id']}/deliver")
    assert r.status_code == 200
    assert r.json()["status"] == "DELIVERED"


async def test_cancel_confirmed_order_restores_stock(client: AsyncClient):
    item = await _create_item(client, stock=10, name="Cancel Confirmed")
    order = await _place_order(client, item["id"], qty=4)

    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    stock_after_confirm = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock_after_confirm["stock_quantity"] == 6

    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    stock_after_cancel = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock_after_cancel["stock_quantity"] == 10  # restored


async def test_cancel_pending_order_does_not_restore_stock(client: AsyncClient):
    item = await _create_item(client, stock=10, name="Cancel Pending")
    order = await _place_order(client, item["id"], qty=4)

    # Cancel before confirming — no stock was deducted
    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 10  # unchanged


async def test_reject_order_when_insufficient_stock(client: AsyncClient):
    item = await _create_item(client, stock=2, name="Low Stock Reject")
    order = await _place_order(client, item["id"], qty=5)

    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 422  # InsufficientStockError

    # Stock must be unchanged
    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 2


async def test_delivered_order_cannot_be_cancelled(client: AsyncClient):
    item = await _create_item(client, stock=10, name="Terminal Delivered")
    order = await _place_order(client, item["id"], qty=1)

    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/ship")
    await client.post(f"/api/v1/orders/{order['id']}/deliver")

    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 422


async def test_stock_movement_audit_trail(client: AsyncClient):
    item = await _create_item(client, stock=10, name="Audit Trail Test")
    order = await _place_order(client, item["id"], qty=3)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/cancel")

    movements = (await client.get(f"/api/v1/stock/{item['id']}/movements")).json()
    types = [m["movement_type"] for m in movements]
    assert "DEDUCTION" in types
    assert "RESTORATION" in types


async def test_rejected_order_status_is_persisted(client: AsyncClient):
    """
    After a confirm fails due to insufficient stock (→ HTTP 422), the order
    status must be REJECTED — not left as PENDING.

    This covers the get_db() commit-on-HTTPException fix: without it the
    transition_status(REJECTED) update was rolled back, leaving the order
    stuck in PENDING forever.
    """
    item = await _create_item(client, stock=1, name="Reject Persist Item")
    order = await _place_order(client, item["id"], qty=99)

    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 422  # Insufficient stock

    # Order must now be REJECTED, not PENDING
    detail = (await client.get(f"/api/v1/orders/{order['id']}")).json()
    assert detail["status"] == "REJECTED", (
        f"Expected REJECTED, got {detail['status']} — "
        "check get_db() commits on HTTPException"
    )

    # Stock untouched
    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 1


async def test_cancel_shipped_order_creates_restoration_movement(client: AsyncClient):
    """
    Cancelling a SHIPPED order must create a RESTORATION movement in the audit
    trail, not just restore the stock_quantity number.
    """
    item = await _create_item(client, stock=10, name="Shipped Cancel Audit")
    order = await _place_order(client, item["id"], qty=4)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/ship")
    await client.post(f"/api/v1/orders/{order['id']}/cancel")

    movements = (await client.get(f"/api/v1/stock/{item['id']}/movements")).json()
    types = [m["movement_type"] for m in movements]
    assert "DEDUCTION" in types
    assert "RESTORATION" in types

    restoration = next(m for m in movements if m["movement_type"] == "RESTORATION")
    assert restoration["quantity_delta"] == 4
    assert restoration["stock_after"] == 10
