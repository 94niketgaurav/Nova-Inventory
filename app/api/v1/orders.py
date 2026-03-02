import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.deps import get_cache
from app.core.cache import CacheService
from app.core.exceptions import (
    ConflictError, InsufficientStockError, InvalidTransitionError, NotFoundError,
)
from app.db.session import get_db
from app.schemas.order import OrderCreate, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(body: OrderCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await OrderService(db).place_order(body.item_id, body.quantity, body.customer_ref)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await OrderService(db).get_order(order_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


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
            raise HTTPException(status_code=404, detail=str(e))
        except InvalidTransitionError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except InsufficientStockError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return transition


confirm_order = _transition_router("confirm")
ship_order = _transition_router("ship")
deliver_order = _transition_router("deliver")
cancel_order = _transition_router("cancel")
