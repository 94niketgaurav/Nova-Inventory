# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import MovementType


class StockResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "item_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "stock_quantity": 45,
                "low_stock_threshold": 10,
                "is_low_stock": False,
            }
        },
    )

    item_id: uuid.UUID
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "item_id": "123e4567-e89b-12d3-a456-426614174000",
                "order_id": "987fbc97-4bed-5078-af07-9141ba07c9f3",
                "movement_type": "DEDUCTION",
                "quantity_delta": -5,
                "stock_before": 50,
                "stock_after": 45,
                "reason": "Stock deducted for order 987fbc97-4bed-5078-af07-9141ba07c9f3",
                "created_at": "2026-03-04T10:00:00Z",
            }
        },
    )

    id: uuid.UUID
    item_id: uuid.UUID
    order_id: uuid.UUID | None
    movement_type: MovementType
    quantity_delta: int
    stock_before: int
    stock_after: int
    reason: str | None
    created_at: datetime


class LowStockAlert(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "name": "Classic Burger",
                "stock_quantity": 3,
                "low_stock_threshold": 10,
            }
        },
    )

    id: uuid.UUID
    name: str
    stock_quantity: int
    low_stock_threshold: int
