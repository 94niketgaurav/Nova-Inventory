# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.analytics import (
    AnalyticsSummary,
    MovementAnalytics,
    OrderAnalytics,
    StockAnalytics,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    svc = AnalyticsService(db)
    return AnalyticsSummary(
        stock=await svc.get_stock_analytics(),
        orders=await svc.get_order_analytics(days=days),
        movements=await svc.get_movement_analytics(days=days),
    )


@router.get("/stock", response_model=StockAnalytics)
async def stock_analytics(db: AsyncSession = Depends(get_db)):
    return await AnalyticsService(db).get_stock_analytics()


@router.get("/orders", response_model=OrderAnalytics)
async def order_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    return await AnalyticsService(db).get_order_analytics(days=days)


@router.get("/movements", response_model=MovementAnalytics)
async def movement_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    return await AnalyticsService(db).get_movement_analytics(days=days)
