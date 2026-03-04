# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
"""
Edge case and boundary tests for the Nova Inventory Service.
Uses the same client fixture from conftest.py.
"""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_item(client: AsyncClient, **overrides) -> dict:
    payload = {
        "name": f"Edge Item {uuid.uuid4().hex[:8]}",
        "price": "9.99",
        "stock_quantity": 20,
        "low_stock_threshold": 5,
        **overrides,
    }
    resp = await client.post("/api/v1/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _place_order(client: AsyncClient, item_id: str, quantity: int = 1) -> dict:
    resp = await client.post("/api/v1/orders", json={"item_id": item_id, "quantity": quantity})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Input Validation ──────────────────────────────────────────────────────────

async def test_create_item_zero_price_rejected(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "Zero Price", "price": "0", "stock_quantity": 10
    })
    assert resp.status_code == 422


async def test_create_item_negative_price_rejected(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "Neg Price", "price": "-1.00", "stock_quantity": 10
    })
    assert resp.status_code == 422


async def test_create_item_negative_stock_rejected(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "Neg Stock", "price": "5.00", "stock_quantity": -1
    })
    assert resp.status_code == 422


async def test_create_item_empty_name_rejected(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "", "price": "5.00", "stock_quantity": 10
    })
    assert resp.status_code == 422


async def test_create_item_duplicate_name_rejected(client: AsyncClient):
    unique_name = f"Duplicate {uuid.uuid4().hex[:8]}"
    await _create_item(client, name=unique_name)
    # Second item with same name must fail
    resp = await client.post("/api/v1/items", json={
        "name": unique_name, "price": "5.00", "stock_quantity": 10
    })
    assert resp.status_code in (409, 422, 500)  # DB unique constraint


async def test_place_order_zero_quantity_rejected(client: AsyncClient):
    item = await _create_item(client)
    resp = await client.post("/api/v1/orders", json={"item_id": item["id"], "quantity": 0})
    assert resp.status_code == 422


async def test_place_order_negative_quantity_rejected(client: AsyncClient):
    item = await _create_item(client)
    resp = await client.post("/api/v1/orders", json={"item_id": item["id"], "quantity": -3})
    assert resp.status_code == 422


async def test_place_order_nonexistent_item(client: AsyncClient):
    resp = await client.post("/api/v1/orders", json={
        "item_id": str(uuid.uuid4()), "quantity": 1
    })
    assert resp.status_code == 404


async def test_confirm_nonexistent_order(client: AsyncClient):
    resp = await client.post(f"/api/v1/orders/{uuid.uuid4()}/confirm")
    assert resp.status_code == 404


async def test_get_stock_nonexistent_item(client: AsyncClient):
    resp = await client.get(f"/api/v1/stock/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_adjust_stock_negative_beyond_available(client: AsyncClient):
    item = await _create_item(client, stock_quantity=5)
    # Try to remove 10 from a stock of 5
    resp = await client.patch(f"/api/v1/items/{item['id']}/stock", json={
        "delta": -10, "reason": "Attempt to go negative"
    })
    assert resp.status_code == 422


async def test_invalid_uuid_in_path(client: AsyncClient):
    resp = await client.get("/api/v1/stock/not-a-valid-uuid")
    assert resp.status_code == 422


# ── State Machine Edge Cases ──────────────────────────────────────────────────

async def test_cannot_confirm_already_confirmed_order(client: AsyncClient):
    item = await _create_item(client)
    order = await _place_order(client, item["id"])
    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    # Second confirm must fail
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert resp.status_code == 422


async def test_cannot_ship_pending_order(client: AsyncClient):
    item = await _create_item(client)
    order = await _place_order(client, item["id"])
    resp = await client.post(f"/api/v1/orders/{order['id']}/ship")
    assert resp.status_code == 422


async def test_cannot_deliver_pending_order(client: AsyncClient):
    item = await _create_item(client)
    order = await _place_order(client, item["id"])
    resp = await client.post(f"/api/v1/orders/{order['id']}/deliver")
    assert resp.status_code == 422


async def test_cannot_confirm_cancelled_order(client: AsyncClient):
    item = await _create_item(client)
    order = await _place_order(client, item["id"])
    await client.post(f"/api/v1/orders/{order['id']}/cancel")
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert resp.status_code == 422


async def test_cannot_confirm_rejected_order(client: AsyncClient):
    # Create item with stock=1, place order for 5 → confirm → rejected
    item = await _create_item(client, stock_quantity=1)
    order = await _place_order(client, item["id"], quantity=5)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")  # → REJECTED
    # Try to confirm again
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert resp.status_code == 422


async def test_cancel_shipped_order_restores_stock(client: AsyncClient):
    item = await _create_item(client, stock_quantity=10)
    order = await _place_order(client, item["id"], quantity=3)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/ship")

    stock_after_ship = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock_after_ship["stock_quantity"] == 7

    r = await client.post(f"/api/v1/orders/{order['id']}/cancel")
    assert r.status_code == 200

    stock_after_cancel = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock_after_cancel["stock_quantity"] == 10  # fully restored


# ── Stock Boundary Cases ──────────────────────────────────────────────────────

async def test_order_exactly_equal_to_stock(client: AsyncClient):
    """Order quantity == stock → confirms, stock goes to exactly 0."""
    item = await _create_item(client, stock_quantity=5)
    order = await _place_order(client, item["id"], quantity=5)
    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED"

    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 0


async def test_order_one_more_than_stock_rejected(client: AsyncClient):
    """Order quantity == stock + 1 → rejected, stock unchanged."""
    item = await _create_item(client, stock_quantity=5)
    order = await _place_order(client, item["id"], quantity=6)
    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 422

    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 5  # unchanged


async def test_zero_stock_item_rejects_any_order(client: AsyncClient):
    item = await _create_item(client, stock_quantity=0)
    order = await _place_order(client, item["id"], quantity=1)
    r = await client.post(f"/api/v1/orders/{order['id']}/confirm")
    assert r.status_code == 422

    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 0


async def test_sequential_orders_deplete_stock_correctly(client: AsyncClient):
    """Two orders, first confirms (qty=3), second confirm fails (qty=3, only 2 left)."""
    item = await _create_item(client, stock_quantity=5)
    order1 = await _place_order(client, item["id"], quantity=3)
    order2 = await _place_order(client, item["id"], quantity=3)

    r1 = await client.post(f"/api/v1/orders/{order1['id']}/confirm")
    assert r1.status_code == 200  # succeeds, 2 left

    r2 = await client.post(f"/api/v1/orders/{order2['id']}/confirm")
    assert r2.status_code == 422  # insufficient

    stock = (await client.get(f"/api/v1/stock/{item['id']}")).json()
    assert stock["stock_quantity"] == 2


# ── List Orders Endpoint ───────────────────────────────────────────────────────

async def test_list_orders_no_filter_returns_all(client: AsyncClient):
    """GET /orders includes all orders created for our test item (DB may have other rows)."""
    item = await _create_item(client)
    o1 = await _place_order(client, item["id"], quantity=1)
    o2 = await _place_order(client, item["id"], quantity=2)
    o3 = await _place_order(client, item["id"], quantity=3)

    r = await client.get("/api/v1/orders")
    assert r.status_code == 200
    # Filter to our item only (DB may have pre-existing rows from other tests)
    our_ids = {o1["id"], o2["id"], o3["id"]}
    returned_ids = {o["id"] for o in r.json()}
    assert our_ids.issubset(returned_ids)


async def test_list_orders_filter_by_status(client: AsyncClient):
    """?status= filter: our confirmed order appears in CONFIRMED, our pending in PENDING."""
    item = await _create_item(client)
    o1 = await _place_order(client, item["id"], quantity=1)
    o2 = await _place_order(client, item["id"], quantity=1)
    await client.post(f"/api/v1/orders/{o1['id']}/confirm")  # o1 → CONFIRMED

    confirmed = (await client.get("/api/v1/orders?status=CONFIRMED")).json()
    pending = (await client.get("/api/v1/orders?status=PENDING")).json()

    # Every returned order must have the correct status
    assert all(o["status"] == "CONFIRMED" for o in confirmed)
    assert all(o["status"] == "PENDING" for o in pending)
    # Our specific orders must be in the right bucket
    assert any(o["id"] == o1["id"] for o in confirmed)
    assert any(o["id"] == o2["id"] for o in pending)


async def test_list_orders_filter_by_customer_ref(client: AsyncClient):
    """?customer_ref= returns only orders matching that ref (unique per test run)."""
    unique_ref = f"TEST-{uuid.uuid4().hex[:8]}"
    item = await _create_item(client)
    await client.post("/api/v1/orders", json={
        "item_id": item["id"], "quantity": 1, "customer_ref": unique_ref,
    })
    await client.post("/api/v1/orders", json={
        "item_id": item["id"], "quantity": 1, "customer_ref": "OTHER-REF",
    })
    await client.post("/api/v1/orders", json={
        "item_id": item["id"], "quantity": 1, "customer_ref": unique_ref,
    })

    r = await client.get(f"/api/v1/orders?customer_ref={unique_ref}")
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) == 2
    assert all(o["customer_ref"] == unique_ref for o in orders)


async def test_list_orders_empty_result_returns_empty_list(client: AsyncClient):
    """A customer_ref that was never used returns [] not 404."""
    nonexistent_ref = f"GHOST-{uuid.uuid4().hex}"
    r = await client.get(f"/api/v1/orders?customer_ref={nonexistent_ref}")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_orders_combined_filters(client: AsyncClient):
    """?status=PENDING&customer_ref=X returns only the single matching order."""
    unique_ref = f"COMBO-{uuid.uuid4().hex[:8]}"
    item = await _create_item(client)
    o1 = (await client.post("/api/v1/orders", json={
        "item_id": item["id"], "quantity": 1, "customer_ref": unique_ref,
    })).json()
    o2 = (await client.post("/api/v1/orders", json={
        "item_id": item["id"], "quantity": 1, "customer_ref": unique_ref,
    })).json()
    # Confirm o2 so it's no longer PENDING
    await client.post(f"/api/v1/orders/{o2['id']}/confirm")

    r = await client.get(f"/api/v1/orders?status=PENDING&customer_ref={unique_ref}")
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) == 1
    assert orders[0]["id"] == o1["id"]


# ── Order Detail Endpoint ─────────────────────────────────────────────────────

async def test_get_order_detail_includes_item_info(client: AsyncClient):
    """GET /orders/{id} returns item_name, item_price, and total_value = price × qty."""
    item = (await client.post("/api/v1/items", json={
        "name": "Detail Price Item", "price": "12.50",
        "stock_quantity": 30, "low_stock_threshold": 5,
    })).json()
    order = await _place_order(client, item["id"], quantity=4)

    r = await client.get(f"/api/v1/orders/{order['id']}")
    assert r.status_code == 200
    d = r.json()
    assert d["item_name"] == "Detail Price Item"
    assert float(d["item_price"]) == 12.50
    assert float(d["total_value"]) == 50.00  # 12.50 × 4


async def test_get_order_detail_movements_populated_after_confirm(client: AsyncClient):
    """After confirm, movements[] must contain exactly one DEDUCTION entry."""
    item = await _create_item(client, stock_quantity=20)
    order = await _place_order(client, item["id"], quantity=5)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")

    r = await client.get(f"/api/v1/orders/{order['id']}")
    assert r.status_code == 200
    d = r.json()
    assert len(d["movements"]) == 1
    mv = d["movements"][0]
    assert mv["movement_type"] == "DEDUCTION"
    assert mv["quantity_delta"] == -5
    assert mv["stock_after"] == d["movements"][0]["stock_before"] - 5


async def test_get_order_detail_movements_after_cancel(client: AsyncClient):
    """After confirm then cancel, movements[] has DEDUCTION + RESTORATION."""
    item = await _create_item(client, stock_quantity=20)
    order = await _place_order(client, item["id"], quantity=3)
    await client.post(f"/api/v1/orders/{order['id']}/confirm")
    await client.post(f"/api/v1/orders/{order['id']}/cancel")

    r = await client.get(f"/api/v1/orders/{order['id']}")
    assert r.status_code == 200
    types = [m["movement_type"] for m in r.json()["movements"]]
    assert "DEDUCTION" in types
    assert "RESTORATION" in types


async def test_get_order_detail_pending_has_no_movements(client: AsyncClient):
    """A newly placed (PENDING) order has zero movements — stock not yet deducted."""
    item = await _create_item(client)
    order = await _place_order(client, item["id"], quantity=2)

    r = await client.get(f"/api/v1/orders/{order['id']}")
    assert r.status_code == 200
    assert r.json()["movements"] == []
