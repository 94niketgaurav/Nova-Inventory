import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.deps import get_cache
from app.core.cache import CacheService
from app.core.exceptions import InsufficientStockError, NotFoundError
from app.db.session import get_db
from app.schemas.item import ItemCreate, ItemResponse, ItemStockAdjust
from app.services.item_service import ItemService

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: ItemCreate,
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
):
    svc = ItemService(db, cache)
    return await svc.create_item(
        name=body.name,
        price=body.price,
        stock_quantity=body.stock_quantity,
        description=body.description,
        low_stock_threshold=body.low_stock_threshold,
    )


@router.get("", response_model=list[ItemResponse])
async def list_items(db: AsyncSession = Depends(get_db)):
    return await ItemService(db).list_items()


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await ItemService(db).get_item(item_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{item_id}/stock", response_model=ItemResponse)
async def adjust_stock(
    item_id: uuid.UUID,
    body: ItemStockAdjust,
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache),
):
    try:
        return await ItemService(db, cache).adjust_stock(item_id, body.delta, body.reason)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InsufficientStockError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
