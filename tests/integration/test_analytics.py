# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
"""
Integration tests for the analytics endpoints.

Covers:
  - GET /api/v1/analytics/stock
  - GET /api/v1/analytics/orders
  - GET /api/v1/analytics/movements
  - GET /api/v1/analytics/summary
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ITEM_PAYLOAD = {
    "name": "Analytics Test Item",
    "description": "Item created for analytics integration tests",
    "price": "9.99",
    "stock_quantity": 100,
    "low_stock_threshold": 5,
}


async def _create_item(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/items", json=ITEM_PAYLOAD)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _place_order(client: AsyncClient, item_id: str, quantity: int = 2) -> dict:
    resp = await client.post(
        "/api/v1/orders",
        json={"item_id": item_id, "quantity": quantity, "customer_ref": "analytics-test"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _confirm_order(client: AsyncClient, order_id: str) -> dict:
    resp = await client.post(f"/api/v1/orders/{order_id}/confirm")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _cancel_order(client: AsyncClient, order_id: str) -> dict:
    resp = await client.post(f"/api/v1/orders/{order_id}/cancel")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_stock_analytics_endpoint(client: AsyncClient):
    """
    POST an item then call GET /api/v1/analytics/stock.
    The response must contain the five StockAnalytics fields and reflect that
    at least one item exists.
    """
    await _create_item(client)

    resp = await client.get("/api/v1/analytics/stock")
    assert resp.status_code == 200, resp.text

    data = resp.json()

    # Verify all expected fields are present
    assert "total_items" in data
    assert "total_units" in data
    assert "total_value" in data
    assert "low_stock_count" in data
    assert "out_of_stock_count" in data

    # At least the one item we just created must be counted
    assert data["total_items"] >= 1
    assert data["total_units"] >= 100  # stock_quantity from ITEM_PAYLOAD
    # total_value is returned as a string by Pydantic's Decimal serialisation
    assert float(data["total_value"]) >= 0.0
    assert data["low_stock_count"] >= 0
    assert data["out_of_stock_count"] >= 0


async def test_order_analytics_endpoint(client: AsyncClient):
    """
    Create an item, place an order, confirm it, then call
    GET /api/v1/analytics/orders.  The response must contain the nine
    OrderAnalytics fields and show at least one confirmed order.
    """
    item = await _create_item(client)
    order = await _place_order(client, item["id"])
    await _confirm_order(client, order["id"])

    resp = await client.get("/api/v1/analytics/orders")
    assert resp.status_code == 200, resp.text

    data = resp.json()

    # Verify all expected fields are present
    assert "total_orders" in data
    assert "pending" in data
    assert "confirmed" in data
    assert "shipped" in data
    assert "delivered" in data
    assert "cancelled" in data
    assert "rejected" in data
    assert "revenue" in data
    assert "refund_value" in data

    # We just confirmed one order, so confirmed count must be >= 1
    assert data["total_orders"] >= 1
    assert data["confirmed"] >= 1
    # Numeric sanity checks
    assert float(data["revenue"]) >= 0.0
    assert float(data["refund_value"]) >= 0.0


async def test_movement_analytics_endpoint(client: AsyncClient):
    """
    Create an item, place an order (PENDING → stock not yet deducted),
    confirm it (stock deducted → DEDUCTION movement), then cancel it
    (stock restored → RESTORATION movement).
    Calling GET /api/v1/analytics/movements must show
    total_deductions >= 1 and total_restorations >= 1.
    """
    item = await _create_item(client)
    order = await _place_order(client, item["id"])
    await _confirm_order(client, order["id"])
    await _cancel_order(client, order["id"])

    resp = await client.get("/api/v1/analytics/movements")
    assert resp.status_code == 200, resp.text

    data = resp.json()

    # Verify all expected fields are present
    assert "total_deductions" in data
    assert "total_restorations" in data
    assert "total_adjustments" in data
    assert "net_stock_change" in data

    # Confirming deducts stock; cancelling a confirmed order restores stock
    assert data["total_deductions"] >= 1
    assert data["total_restorations"] >= 1
    assert isinstance(data["total_adjustments"], int)
    assert isinstance(data["net_stock_change"], int)


async def test_summary_endpoint(client: AsyncClient):
    """
    Call GET /api/v1/analytics/summary and verify the response contains the
    three top-level keys (stock, orders, movements) each with their nested
    analytics fields.
    """
    resp = await client.get("/api/v1/analytics/summary")
    assert resp.status_code == 200, resp.text

    data = resp.json()

    # Top-level keys must exist
    assert "stock" in data, "Missing 'stock' key in summary response"
    assert "orders" in data, "Missing 'orders' key in summary response"
    assert "movements" in data, "Missing 'movements' key in summary response"

    # Spot-check nested keys for each section
    stock = data["stock"]
    assert "total_items" in stock
    assert "total_units" in stock
    assert "total_value" in stock
    assert "low_stock_count" in stock
    assert "out_of_stock_count" in stock

    orders = data["orders"]
    assert "total_orders" in orders
    assert "pending" in orders
    assert "confirmed" in orders
    assert "shipped" in orders
    assert "delivered" in orders
    assert "cancelled" in orders
    assert "rejected" in orders
    assert "revenue" in orders
    assert "refund_value" in orders

    movements = data["movements"]
    assert "total_deductions" in movements
    assert "total_restorations" in movements
    assert "total_adjustments" in movements
    assert "net_stock_change" in movements
