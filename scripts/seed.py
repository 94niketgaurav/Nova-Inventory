# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
"""
Seed script — populates the database with realistic items and orders
to exercise all API endpoints, order states, and analytics.

Usage:
    uv run python scripts/seed.py
    uv run python scripts/seed.py --base-url http://localhost:8000
"""

import argparse
import sys

import httpx

# ── Items to seed ─────────────────────────────────────────────────────────────
# Covers: normal stock, low stock, zero stock, various prices, thresholds
ITEMS = [
    {
        "name": "Pepperoni Pizza",
        "description": "Spicy pepperoni with extra cheese",
        "price": "14.99",
        "stock_quantity": 40,
        "low_stock_threshold": 10,
    },
    {
        "name": "Caesar Salad",
        "description": "Romaine lettuce, parmesan, croutons",
        "price": "8.99",
        "stock_quantity": 7,           # near threshold → low stock
        "low_stock_threshold": 8,
    },
    {
        "name": "Chicken Burger",
        "description": "Crispy fried chicken with coleslaw",
        "price": "11.50",
        "stock_quantity": 25,
        "low_stock_threshold": 5,
    },
    {
        "name": "Veggie Wrap",
        "description": "Grilled vegetables with hummus",
        "price": "9.99",
        "stock_quantity": 18,
        "low_stock_threshold": 5,
    },
    {
        "name": "Fish & Chips",
        "description": "Beer-battered cod with thick-cut chips",
        "price": "13.50",
        "stock_quantity": 3,           # below threshold → low stock
        "low_stock_threshold": 10,
    },
    {
        "name": "Chocolate Lava Cake",
        "description": "Warm chocolate cake with vanilla ice cream",
        "price": "6.99",
        "stock_quantity": 20,
        "low_stock_threshold": 5,
    },
    {
        "name": "Beef Steak",
        "description": "250g prime ribeye, medium rare",
        "price": "24.99",
        "stock_quantity": 12,
        "low_stock_threshold": 5,
    },
    {
        "name": "Garlic Bread",
        "description": "Toasted sourdough with garlic butter",
        "price": "4.50",
        "stock_quantity": 0,           # out of stock → orders must be rejected
        "low_stock_threshold": 5,
    },
    {
        "name": "Sparkling Water",
        "description": "500ml chilled sparkling water",
        "price": "2.99",
        "stock_quantity": 100,
        "low_stock_threshold": 20,
    },
    {
        "name": "Craft Beer",
        "description": "Local IPA, 330ml",
        "price": "5.99",
        "stock_quantity": 6,           # below threshold → low stock
        "low_stock_threshold": 10,
    },
    {
        "name": "Premium Coffee",
        "description": "Single-origin espresso, served hot or iced",
        "price": "3.49",
        "stock_quantity": 50,
        "low_stock_threshold": 10,
    },
]


def post(client: httpx.Client, path: str, **kwargs) -> dict:
    r = client.post(path, **kwargs)
    if r.status_code not in (200, 201):
        print(f"  ✗ POST {path} → {r.status_code}: {r.text[:120]}")
        return {}
    return r.json()


def transition(client: httpx.Client, order_id: str, action: str) -> dict:
    r = client.post(f"/api/v1/orders/{order_id}/{action}")
    if r.status_code not in (200, 201):
        print(f"  ✗ {action} {order_id} → {r.status_code}: {r.text[:120]}")
        return {}
    return r.json()


def run(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:

        # ── 1. Health check ──────────────────────────────────────────────────
        health = client.get("/health").json()
        print(f"Server: {health}\n")

        # ── 2. Seed items ────────────────────────────────────────────────────
        print("=== Creating items ===")
        item_map: dict[str, str] = {}   # name → id

        # keep the existing Margherita if it's already there
        existing = {i["name"]: i["id"] for i in client.get("/api/v1/items").json()}
        item_map.update(existing)

        for item in ITEMS:
            if item["name"] in item_map:
                print(f"  ↷  {item['name']} already exists — skipping")
                continue
            result = post(client, "/api/v1/items", json=item)
            if result:
                item_map[result["name"]] = result["id"]
                print(f"  ✓  {result['name']}  id={result['id']}  stock={result['stock_quantity']}")

        print(f"\nTotal items: {len(item_map)}\n")

        # ── 3. Create orders in every possible state ─────────────────────────
        print("=== Creating orders ===")

        def order(name: str, qty: int, ref: str) -> str:
            """Place an order and return its id (empty string on failure)."""
            iid = item_map.get(name)
            if not iid:
                print(f"  ✗ Item '{name}' not found")
                return ""
            r = post(client, "/api/v1/orders",
                     json={"item_id": iid, "quantity": qty, "customer_ref": ref})
            return r.get("id", "")

        # DELIVERED — full lifecycle
        print("\n-- Delivered orders (revenue) --")
        for name, qty, ref in [
            ("Pepperoni Pizza",    3,  "CUST-101"),
            ("Chicken Burger",     2,  "CUST-102"),
            ("Beef Steak",         1,  "CUST-103"),
            ("Premium Coffee",     4,  "CUST-104"),
            ("Sparkling Water",    6,  "CUST-105"),
        ]:
            oid = order(name, qty, ref)
            if oid:
                transition(client, oid, "confirm")
                transition(client, oid, "ship")
                transition(client, oid, "deliver")
                print(f"  ✓  DELIVERED  {qty}x {name}  [{ref}]")

        # SHIPPED — confirmed and on the way
        print("\n-- Shipped orders (in transit) --")
        for name, qty, ref in [
            ("Chocolate Lava Cake", 2, "CUST-201"),
            ("Veggie Wrap",         3, "CUST-202"),
        ]:
            oid = order(name, qty, ref)
            if oid:
                transition(client, oid, "confirm")
                transition(client, oid, "ship")
                print(f"  ✓  SHIPPED    {qty}x {name}  [{ref}]")

        # CONFIRMED — stock deducted, not yet shipped
        print("\n-- Confirmed orders (awaiting dispatch) --")
        for name, qty, ref in [
            ("Pepperoni Pizza",  2, "CUST-301"),
            ("Craft Beer",       2, "CUST-302"),
        ]:
            oid = order(name, qty, ref)
            if oid:
                transition(client, oid, "confirm")
                print(f"  ✓  CONFIRMED  {qty}x {name}  [{ref}]")

        # PENDING — placed but not yet confirmed
        print("\n-- Pending orders --")
        for name, qty, ref in [
            ("Caesar Salad",   2, "CUST-401"),
            ("Fish & Chips",   1, "CUST-402"),
        ]:
            oid = order(name, qty, ref)
            if oid:
                print(f"  ✓  PENDING    {qty}x {name}  [{ref}]")

        # CANCELLED after confirm — stock should be restored
        print("\n-- Cancelled orders (stock restored) --")
        for name, qty, ref in [
            ("Chicken Burger",  3, "CUST-501"),
            ("Premium Coffee",  2, "CUST-502"),
        ]:
            oid = order(name, qty, ref)
            if oid:
                transition(client, oid, "confirm")
                transition(client, oid, "cancel")
                print(f"  ✓  CANCELLED  {qty}x {name}  [{ref}]  (stock restored)")

        # REJECTED — order more than available stock
        print("\n-- Rejected orders (insufficient stock) --")
        for name, qty, ref in [
            ("Garlic Bread",  5, "CUST-601"),   # stock = 0
            ("Fish & Chips", 99, "CUST-602"),   # way over stock
        ]:
            oid = order(name, qty, ref)
            if oid:
                r = client.post(f"/api/v1/orders/{oid}/confirm")
                status = r.json().get("detail", r.status_code)
                print(f"  ✓  REJECTED   {qty}x {name}  [{ref}]  → {status}")

        # ── 4. Print final analytics ─────────────────────────────────────────
        print("\n=== Analytics Summary ===")
        summary = client.get("/api/v1/analytics/summary").json()
        s = summary["stock"]
        o = summary["orders"]
        print(f"  Items        : {s['total_items']}  ({s['out_of_stock_count']} out-of-stock, {s['low_stock_count']} low-stock)")
        print(f"  Stock value  : ₹{s['total_value']}")
        print(f"  Orders       : {o['total_orders']} total")
        print(f"    Delivered  : {o['delivered']}")
        print(f"    Shipped    : {o['shipped']}")
        print(f"    Confirmed  : {o['confirmed']}")
        print(f"    Pending    : {o['pending']}")
        print(f"    Cancelled  : {o['cancelled']}")
        print(f"    Rejected   : {o['rejected']}")
        print(f"  Revenue      : ₹{o['revenue']}")
        print(f"  Refunds      : ₹{o['refund_value']}")

        print("\n=== Low Stock Alerts ===")
        alerts = client.get("/api/v1/stock/alerts/low").json()
        if alerts:
            for a in alerts:
                print(f"  ⚠  {a['name']:25s}  stock={a['stock_quantity']}  threshold={a['low_stock_threshold']}")
        else:
            print("  (none)")

        print("\nDone. Visit http://localhost:8000/docs to explore the data interactively.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Nova Inventory Service")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    run(args.base_url)
