# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(..., gt=0, decimal_places=2)
    stock_quantity: int = Field(..., ge=0)
    low_stock_threshold: int = Field(default=10, ge=0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Classic Burger",
                "description": "200g beef patty with lettuce and tomato",
                "price": "12.99",
                "stock_quantity": 50,
                "low_stock_threshold": 10,
            }
        }
    )


class ItemStockAdjust(BaseModel):
    delta: int = Field(..., description="Positive to add, negative to remove")
    reason: str = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "delta": -5,
                "reason": "Damaged goods removed from stock",
            }
        }
    )


class ItemResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "name": "Classic Burger",
                "description": "200g beef patty with lettuce and tomato",
                "price": "12.99",
                "stock_quantity": 50,
                "low_stock_threshold": 10,
                "is_low_stock": False,
                "version": 1,
                "created_at": "2026-03-04T10:00:00Z",
                "updated_at": "2026-03-04T10:00:00Z",
            }
        },
    )

    id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool
    version: int
    created_at: datetime
    updated_at: datetime
