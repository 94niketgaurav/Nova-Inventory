import uuid
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from app.domain.enums import OrderStatus


class OrderCreate(BaseModel):
    item_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    customer_ref: str | None = Field(default=None, max_length=255)


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
