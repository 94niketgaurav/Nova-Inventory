# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from decimal import Decimal

from pydantic import BaseModel


class StockAnalytics(BaseModel):
    total_items: int
    total_units: int
    total_value: Decimal
    low_stock_count: int
    out_of_stock_count: int


class OrderAnalytics(BaseModel):
    total_orders: int
    pending: int
    confirmed: int
    shipped: int
    delivered: int
    cancelled: int
    rejected: int
    revenue: Decimal        # sum of price * quantity for DELIVERED orders
    refund_value: Decimal   # sum of price * quantity for CANCELLED orders (that had stock deducted)


class MovementAnalytics(BaseModel):
    total_deductions: int
    total_restorations: int
    total_adjustments: int
    net_stock_change: int   # sum of quantity_delta across all movements


class AnalyticsSummary(BaseModel):
    stock: StockAnalytics
    orders: OrderAnalytics
    movements: MovementAnalytics
