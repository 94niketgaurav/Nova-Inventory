# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_cache
from app.core.cache import CacheService
from app.core.exceptions import (
    ConflictError,
    InsufficientStockError,
    InvalidTransitionError,
    NotFoundError,
)
from app.db.session import get_db
from app.domain.enums import OrderStatus
from app.schemas.order import OrderCreate, OrderDetailResponse, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get(
    "",
    response_model=list[OrderResponse],
    summary="List orders",
    description=(
        "Returns orders with optional filters. "
        "Use `date` for a specific calendar day, or `from_date`/`to_date` for a custom range. "
        "All datetime values are UTC."
    ),
)
async def list_orders(
    order_status: OrderStatus | None = Query(default=None, alias="status", description="Filter by order status"),
    filter_date: date | None = Query(default=None, alias="date", description="Exact calendar day (YYYY-MM-DD, UTC)"),
    from_date: datetime | None = Query(default=None, description="Range start (ISO 8601 UTC)"),
    to_date: datetime | None = Query(default=None, description="Range end (ISO 8601 UTC)"),
    customer_ref: str | None = Query(default=None, description="Filter by customer reference"),
    db: AsyncSession = Depends(get_db),
):
    if filter_date:
        from_dt = datetime.combine(filter_date, time.min).replace(tzinfo=timezone.utc)
        to_dt = datetime.combine(filter_date, time.max).replace(tzinfo=timezone.utc)
    else:
        from_dt = from_date
        to_dt = to_date
    return await OrderService(db).list_orders(
        status=order_status, from_dt=from_dt, to_dt=to_dt, customer_ref=customer_ref
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(body: OrderCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await OrderService(db).place_order(body.item_id, body.quantity, body.customer_ref)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get(
    "/{order_id}",
    response_model=OrderDetailResponse,
    summary="Get order detail",
    description="Full order detail including item name, unit price, total value, and stock movement audit trail.",
)
async def get_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await OrderService(db).get_order_detail(order_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


def _transition_router(action: str):
    """Factory to reduce boilerplate for simple state transitions."""

    @router.post(f"/{{order_id}}/{action}", response_model=OrderResponse)
    async def transition(
        order_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        cache: CacheService = Depends(get_cache),
    ):
        svc = OrderService(db, cache)
        method = getattr(svc, f"{action}_order")
        try:
            return await method(order_id)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except InvalidTransitionError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except InsufficientStockError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    return transition


confirm_order = _transition_router("confirm")
ship_order = _transition_router("ship")
deliver_order = _transition_router("deliver")
cancel_order = _transition_router("cancel")
