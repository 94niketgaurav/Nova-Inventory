# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.schemas.analytics import (
    AnalyticsSummary,
    MovementAnalytics,
    OrderAnalytics,
    StockAnalytics,
)
from app.schemas.item import ItemCreate, ItemResponse
from app.schemas.order import OrderCreate


def test_item_create_validation():
    item = ItemCreate(name="Burger", price=Decimal("9.99"), stock_quantity=50)
    assert item.name == "Burger"
    assert item.low_stock_threshold == 10  # default


def test_order_create_validation():
    order = OrderCreate(item_id=uuid.uuid4(), quantity=2)
    assert order.quantity == 2
    assert order.customer_ref is None


def test_stock_response_from_attributes():
    now = datetime.now(UTC)

    class FakeItem:
        id = uuid.uuid4()
        name = "Burger"
        stock_quantity = 5
        low_stock_threshold = 10
        is_low_stock = True
        price = Decimal("9.99")
        description = None
        version = 1
        created_at = now
        updated_at = now

    resp = ItemResponse.model_validate(FakeItem())
    assert resp.is_low_stock is True
    assert resp.stock_quantity == 5


def test_analytics_summary():
    summary = AnalyticsSummary(
        stock=StockAnalytics(total_items=5, total_units=100, total_value=Decimal("500"), low_stock_count=1, out_of_stock_count=0),
        orders=OrderAnalytics(total_orders=10, pending=2, confirmed=3, shipped=2, delivered=2, cancelled=1, rejected=0, revenue=Decimal("200"), refund_value=Decimal("50")),
        movements=MovementAnalytics(total_deductions=5, total_restorations=1, total_adjustments=2, net_stock_change=-4),
    )
    assert summary.stock.total_items == 5
    assert summary.orders.revenue == Decimal("200")
