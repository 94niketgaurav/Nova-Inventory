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
