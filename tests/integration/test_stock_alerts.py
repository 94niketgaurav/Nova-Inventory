# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_low_stock_alert_returns_items_below_threshold(client: AsyncClient):
    # Create item below threshold
    low_resp = await client.post("/api/v1/items", json={
        "name": "Low Item Alert",
        "price": "5.00",
        "stock_quantity": 3,
        "low_stock_threshold": 10,
    })
    assert low_resp.status_code == 201

    # Create item above threshold
    ok_resp = await client.post("/api/v1/items", json={
        "name": "OK Item Alert",
        "price": "5.00",
        "stock_quantity": 50,
        "low_stock_threshold": 10,
    })
    assert ok_resp.status_code == 201

    alerts = (await client.get("/api/v1/stock/alerts/low")).json()
    alert_ids = [a["id"] for a in alerts]

    assert low_resp.json()["id"] in alert_ids
    assert ok_resp.json()["id"] not in alert_ids


async def test_item_at_threshold_is_included_in_alerts(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "At Threshold Alert",
        "price": "5.00",
        "stock_quantity": 10,
        "low_stock_threshold": 10,
    })
    assert resp.status_code == 201

    alerts = (await client.get("/api/v1/stock/alerts/low")).json()
    alert_ids = [a["id"] for a in alerts]
    assert resp.json()["id"] in alert_ids


async def test_stock_level_endpoint(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "Stock Level Test",
        "price": "5.00",
        "stock_quantity": 25,
        "low_stock_threshold": 10,
    })
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    stock = (await client.get(f"/api/v1/stock/{item_id}")).json()
    assert stock["stock_quantity"] == 25
    assert stock["is_low_stock"] is False


async def test_manual_stock_adjustment_reflected_in_stock_level(client: AsyncClient):
    resp = await client.post("/api/v1/items", json={
        "name": "Adjustment Test",
        "price": "5.00",
        "stock_quantity": 20,
        "low_stock_threshold": 5,
    })
    item_id = resp.json()["id"]

    # Reduce stock below threshold
    adj = await client.patch(f"/api/v1/items/{item_id}/stock", json={
        "delta": -17,
        "reason": "Manual shrinkage",
    })
    assert adj.status_code == 200

    stock = (await client.get(f"/api/v1/stock/{item_id}")).json()
    assert stock["stock_quantity"] == 3
    assert stock["is_low_stock"] is True

    # Movement audit trail should show the adjustment
    movements = (await client.get(f"/api/v1/stock/{item_id}/movements")).json()
    types = [m["movement_type"] for m in movements]
    assert "ADJUSTMENT" in types
