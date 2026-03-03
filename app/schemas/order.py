# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import OrderStatus


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
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    quantity: int
    status: OrderStatus
    customer_ref: str | None
    version: int
    created_at: datetime
    updated_at: datetime
