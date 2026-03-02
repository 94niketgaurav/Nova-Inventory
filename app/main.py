import time
import uuid
from contextlib import asynccontextmanager
import structlog
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from app.api.v1.router import api_router
from app.core.cache import close_redis
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import close_engine, get_engine
from app.middleware import ApiKeyMiddleware

configure_logging()
logger = structlog.get_logger(__name__)

# ── Rate limiter — backed by Redis (same URL as cache) ────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
)


async def _validate_migrations() -> None:
    """
    Abort startup if any migration has not been applied.
    Prevents running stale code against an out-of-date schema.
    """
    engine = get_engine()
    alembic_cfg = AlembicConfig("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    expected_heads = set(script.get_heads())

    async with engine.connect() as conn:
        def _get_current(sync_conn):
            ctx = MigrationContext.configure(sync_conn)
            return set(ctx.get_current_heads())

        current_heads = await conn.run_sync(_get_current)

    if current_heads != expected_heads:
        missing = expected_heads - current_heads
        raise RuntimeError(
            f"Database is not up to date. Missing revisions: {missing}. "
            f"Run: uv run alembic upgrade head"
        )
    logger.info("migrations_ok", heads=sorted(current_heads))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", environment=settings.environment, db_host=settings.db_host)
    await _validate_migrations()
    yield
    logger.info("shutdown")
    await close_engine()
    await close_redis()


app = FastAPI(
    title="Nova Inventory Service",
    description=(
        "Inventory & Stock Consistency Service — "
        "atomic stock management, order lifecycle, write-through cache, analytics"
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ── Middleware (registered in reverse order — last registered = outermost) ────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    ApiKeyMiddleware,
    require_auth=settings.require_auth,
    valid_keys=settings.valid_api_keys,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": "0.1.0"}
