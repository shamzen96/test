"""Main FastAPI application entry point with dynamic tenant mounting."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.core.config import settings
from app.core.exceptions import TenantException
from app.core.logging import logger
from app.core.middleware import RequestContextMiddleware
from app.database.session import init_db
from app.routing.tenant_dispatcher import TenantDispatcher
from app.routing.tenant_router import DynamicTenantMount


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle management."""
    logger.info("Initializing database schemas and seed records...")
    try:
        await init_db()
        logger.info("Database initialization completed.")
    except Exception as exc:
        logger.error(f"Database initialization error (application will proceed): {exc}")

    yield

    logger.info("Shutting down application...")


class DynamicTenantFastAPI(FastAPI):
    """FastAPI subclass that automatically intercepts parameterized paths in mount()."""

    def mount(self, path: str, app: ASGIApp, name: str | None = None) -> None:
        if "{" in path and "}" in path:
            logger.info(f"Mounting dynamic parameterized route: {path} -> {app.__class__.__name__}")
            route = DynamicTenantMount(path=path, app=app, name=name)
            self.router.routes.append(route)
        else:
            super().mount(path, app, name=name)


def create_application() -> FastAPI:
    """Factory creating and configuring the primary FastAPI application."""
    app = DynamicTenantFastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Production-Ready Dynamic Multi-Tenant FastAPI Application with Dynamic /{tenant} Mounting",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    # Exception Handlers
    @app.exception_handler(TenantException)
    async def tenant_exception_handler(request: Request, exc: TenantException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # 1. Register explicit root and administrative routes first
    app.include_router(health_router)
    app.include_router(admin_router)

    # 2. Register dynamic /{tenant} mounting pattern
    # Routes all other /{tenant}/* requests dynamically to TenantDispatcher
    app.mount("/{tenant}", TenantDispatcher())

    return app


app = create_application()
