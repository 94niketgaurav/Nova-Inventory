# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from fastapi import APIRouter

from app.api.v1 import analytics, items, orders, stock

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(items.router)
api_router.include_router(orders.router)
api_router.include_router(stock.router)
api_router.include_router(analytics.router)
