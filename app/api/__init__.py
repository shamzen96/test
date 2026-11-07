"""API routers package."""

from app.api.admin import router as admin_router
from app.api.health import router as health_router

__all__ = ["health_router", "admin_router"]
