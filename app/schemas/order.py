# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import OrderStatus
from app.schemas.stock import StockMovementResponse


class OrderCreate(BaseModel):
    item_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    customer_ref: str | None = Field(default=None, max_length=255)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "item_id": "123e4567-e89b-12d3-a456-426614174000",
                "quantity": 2,
                "customer_ref": "CUST-001",
            }
        }
    )


class OrderResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "item_id": "123e4567-e89b-12d3-a456-426614174000",
                "quantity": 2,
                "status": "PENDING",
                "customer_ref": "CUST-001",
                "version": 1,
                "created_at": "2026-03-04T10:00:00Z",
                "updated_at": "2026-03-04T10:00:00Z",
            }
        },
    )

    id: uuid.UUID
    item_id: uuid.UUID
    quantity: int
    status: OrderStatus
    customer_ref: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class OrderDetailResponse(BaseModel):
    """Rich order view — includes item details and stock movement audit trail."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "item_id": "123e4567-e89b-12d3-a456-426614174000",
                "item_name": "Classic Burger",
                "item_price": "12.99",
                "quantity": 2,
                "total_value": "25.98",
                "status": "DELIVERED",
                "customer_ref": "CUST-001",
                "version": 3,
                "created_at": "2026-03-04T10:00:00Z",
                "updated_at": "2026-03-04T10:30:00Z",
                "movements": [],
            }
        },
    )

    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str
    item_price: Decimal
    quantity: int
    total_value: Decimal
    status: OrderStatus
    customer_ref: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    movements: list[StockMovementResponse]
