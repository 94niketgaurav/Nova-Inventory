import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.domain.enums import MovementType


class StockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: uuid.UUID
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    stock_quantity: int
    low_stock_threshold: int
