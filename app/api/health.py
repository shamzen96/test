"""Root health and system inspection endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.session import get_db

router = APIRouter(tags=["System Health"])


@router.get("/health", summary="Root System Health")
async def root_health(session: AsyncSession = Depends(get_db)):
    """Health check validating application runtime and database connectivity."""
    db_healthy = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_healthy = False

    return {
        "status": "healthy" if db_healthy else "degraded",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database": "connected" if db_healthy else "unavailable",
    }


@router.get("/", summary="Root Welcome & Documentation Links")
async def root_index():
    return {
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
        "pattern": "/{tenant}/*",
    }
