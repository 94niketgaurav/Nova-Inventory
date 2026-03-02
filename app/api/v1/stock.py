import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.deps import get_cache
from app.core.cache import CacheService
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.schemas.stock import LowStockAlert, StockMovementResponse, StockResponse
from app.services.stock_service import StockService

router = APIRouter(prefix="/stock", tags=["stock"])
limiter = Limiter(key_func=get_remote_address)


@router.get("/alerts/low", response_model=list[LowStockAlert])
async def low_stock_alerts(db: AsyncSession = Depends(get_db)):
    return await StockService(db).get_low_stock_items()


@router.get("/{item_id}", response_model=StockResponse)
@limiter.limit(settings.rate_limit_stock_read)
async def get_stock(
    request: Request,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
):
    try:
        item = await StockService(db, cache).get_stock(item_id)
        return StockResponse(
            item_id=item.id,
            stock_quantity=item.stock_quantity,
            low_stock_threshold=item.low_stock_threshold,
            is_low_stock=item.is_low_stock,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{item_id}/movements", response_model=list[StockMovementResponse])
async def get_movements(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await StockService(db).get_movements(item_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
