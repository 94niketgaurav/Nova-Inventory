# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class StockAnalytics(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_items": 12,
                "total_units": 285,
                "total_value": "2458.75",
                "low_stock_count": 3,
                "out_of_stock_count": 1,
            }
        }
    )

    total_items: int
    total_units: int
    total_value: Decimal
    low_stock_count: int
    out_of_stock_count: int


class OrderAnalytics(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_orders": 17,
                "pending": 2,
                "confirmed": 2,
                "shipped": 2,
                "delivered": 5,
                "cancelled": 2,
                "rejected": 2,
                "revenue": "189.81",
                "refund_value": "46.99",
            }
        }
    )

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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_deductions": 7,
                "total_restorations": 2,
                "total_adjustments": 12,
                "net_stock_change": -15,
            }
        }
    )

    total_deductions: int
    total_restorations: int
    total_adjustments: int
    net_stock_change: int   # sum of quantity_delta across all movements


class AnalyticsSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "stock": {
                    "total_items": 12,
                    "total_units": 285,
                    "total_value": "2458.75",
                    "low_stock_count": 3,
                    "out_of_stock_count": 1,
                },
                "orders": {
                    "total_orders": 17,
                    "pending": 2,
                    "confirmed": 2,
                    "shipped": 2,
                    "delivered": 5,
                    "cancelled": 2,
                    "rejected": 2,
                    "revenue": "189.81",
                    "refund_value": "46.99",
                },
                "movements": {
                    "total_deductions": 7,
                    "total_restorations": 2,
                    "total_adjustments": 12,
                    "net_stock_change": -15,
                },
            }
        }
    )

    stock: StockAnalytics
    orders: OrderAnalytics
    movements: MovementAnalytics
